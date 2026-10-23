"""Opt-in base/LoRA residency; role tokenizers and token accounting stay separate."""

from contextlib import nullcontext
import json
from pathlib import Path

from .model_backend import LocalBackend


def compatible_base_adapter(paths):
    """Only plain, non-base-mutating local LoRA exports qualify for this path."""
    if set(paths) != {"actor", "analyzer"}:
        return False
    actor, analyzer = (Path(paths[role]).resolve() for role in ("actor", "analyzer"))
    if actor == analyzer or (actor / "adapter_config.json").exists() \
            or (analyzer / "tiny_base_recipe.json").exists():
        return False
    try:
        config = json.loads((analyzer / "adapter_config.json").read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            return False
        base = Path(config["base_model_name_or_path"])
        # Hub identifiers and relative base paths are deliberately not inferred.
        return base.is_absolute() and base.resolve() == actor and actor.is_dir() \
            and config.get("peft_type") == "LORA" and config.get("bias", "none") == "none" \
            and not config.get("lora_bias", False) and not config.get("modules_to_save") \
            and not config.get("trainable_token_indices") and not config.get("layer_replication") \
            and type(config.get("init_lora_weights", True)) is bool
    except (OSError, ValueError, KeyError, TypeError):
        return False


class SharedRoleBackend(LocalBackend):
    """One unmerged base plus adapter, sequential calls, no cross-call KV cache."""

    def __init__(self, paths, device="cpu", max_new_tokens=256, token_budget=20000,
                 ledger=None, context_limit=None):
        if not compatible_base_adapter(paths):
            raise ValueError("Shared residency requires a matching non-mutating local LoRA export")
        super().__init__(paths["actor"], device, max_new_tokens, token_budget,
                         ledger=ledger, context_limit=context_limit)
        try:
            from peft import PeftModel
            from .neural import dependencies
            _, transformers = dependencies()
            self.role_tokenizers = {"actor": self.tokenizer, "analyzer":
                transformers.AutoTokenizer.from_pretrained(paths["analyzer"], local_files_only=True,
                                                           trust_remote_code=False)}
            self.model = PeftModel.from_pretrained(self.model, paths["analyzer"], is_trainable=False)
            self.model.to(device).eval()
            configured = self.model.generation_config.eos_token_id
            configured = list(configured) if isinstance(configured, (list, tuple)) else [configured]
            self.role_eos = {role: list(dict.fromkeys(i for i in [tok.eos_token_id] + configured if i is not None))
                             for role, tok in self.role_tokenizers.items()}
        except Exception:
            self.close()
            raise

    def complete(self, prompt, role="model"):
        if role not in self.role_tokenizers:
            raise ValueError("Unknown shared-backend role")
        previous_tokenizer, previous_eos = self.tokenizer, self.eos_ids
        self.tokenizer, self.eos_ids = self.role_tokenizers[role], self.role_eos[role]
        try:
            with self.model.disable_adapter() if role == "actor" else nullcontext():
                return super().complete(prompt, role=role)
        finally:
            self.tokenizer, self.eos_ids = previous_tokenizer, previous_eos
