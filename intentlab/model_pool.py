"""Separate actor/analyzer identities with at most one resident local model.

Switching full models includes reload overhead; all such overhead is recorded.
This is a memory-conscious correctness path, not a throughput optimization.
"""

from pathlib import Path
import time

from .budget import TokenLedger
from .model_backend import LocalBackend
from .gpu_lease import ensure_gpu_lease


class RoleBackend:
    def __init__(self, pool, role):
        self.pool, self.role = pool, role

    def complete(self, prompt):
        return self.pool.complete(self.role, prompt)


class LocalModelPool:
    def __init__(self, paths, device="cpu", max_new_tokens=256, token_budget=20000, factory=None, context_limit=None,
                 share_base_adapter=False):
        if not paths or set(paths) - {"actor", "analyzer"}:
            raise ValueError("Expected actor and/or analyzer model paths")
        self.paths = {role: str(Path(path).resolve()) for role, path in paths.items()}
        self.device, self.maximum = device, max_new_tokens
        if device == "cuda":
            ensure_gpu_lease()
        if context_limit is not None and (type(context_limit) is not int or context_limit < 1):
            raise ValueError("Context limit must be positive")
        self.context_limit = context_limit
        self.ledger = TokenLedger(token_budget)
        self.factory = factory or LocalBackend
        # Off until development equivalence and residency policy are validated.
        # Injected factories keep their existing reload semantics.
        from .shared_role_backend import compatible_base_adapter
        self.shared_residency = bool(share_base_adapter and factory is None and compatible_base_adapter(self.paths))
        self.current, self.current_path = None, None
        self.reset()

    def role(self, role):
        if role not in self.paths:
            raise ValueError("Role has no configured model")
        return RoleBackend(self, role)

    def reset(self):
        self.ledger.reset()
        self.generations, self.loads = [], []
        if self.current is not None:
            self.current.reset()

    def close(self):
        if self.current is not None:
            self.current.close()
            self.current = None
            self.current_path = None

    def complete(self, role, prompt):
        if role not in self.paths:
            raise ValueError("Unknown model role")
        if self.device == "cuda":
            ensure_gpu_lease()
        path = self.paths[role]
        resident_key = "shared-base-adapter" if self.shared_residency else path
        if self.current_path != resident_key:
            self.close()
            started = time.perf_counter()
            try:
                kwargs = {"ledger": self.ledger}
                if self.context_limit is not None:
                    kwargs["context_limit"] = self.context_limit
                if self.shared_residency:
                    from .shared_role_backend import SharedRoleBackend
                    self.current = SharedRoleBackend(self.paths, self.device, self.maximum, self.ledger.limit, **kwargs)
                else:
                    self.current = self.factory(path, self.device, self.maximum, self.ledger.limit, **kwargs)
                self.current_path = resident_key
            except Exception as exc:
                self.loads.append({"role": role, "path": path, "status": "error", "error": type(exc).__name__,
                                   "seconds": time.perf_counter() - started})
                raise
            self.loads.append({"role": role, "path": path, "status": "loaded",
                               "seconds": time.perf_counter() - started})
        # A resident backend may have served another task. Shared task accounting
        # is authoritative; reset only its legacy per-backend counters per call.
        self.current.reset()
        try:
            result = self.current.complete(prompt, role=role)
        except Exception:
            self.generations.extend(dict(row, role=role, model_path=path) for row in self.current.generations)
            raise
        self.generations.extend(dict(row, role=role, model_path=path) for row in self.current.generations)
        return result

    def snapshot(self):
        return {"shared_token_ledger": self.ledger.snapshot(), "models": dict(self.paths),
                "context_limit": self.context_limit,
                "model_loads": list(self.loads), "generations": list(self.generations),
                "resident_model_limit": 1,
                "residency_strategy": "shared-base-adapter" if self.shared_residency else "reload-by-path"}
