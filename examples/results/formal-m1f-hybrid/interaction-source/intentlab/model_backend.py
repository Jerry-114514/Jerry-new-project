"""Local Hugging Face generation, strict JSON interfaces and bounded token use."""

import json
import gc
from pathlib import Path

from .analysis import REQUIREMENTS
from .core import canonical, digest
from .neural import dependencies
from .sft_data import analysis_prompt
from .prompts import prompt_ids
from .budget import BudgetExceeded, TokenLedger


class LocalBackend:
    def __init__(self, model_path, device="cpu", max_new_tokens=256, token_budget=20000, ledger=None, context_limit=None):
        if max_new_tokens < 1 or token_budget < 1:
            raise ValueError("Positive generation and token budgets required")
        if context_limit is not None and (type(context_limit) is not int or context_limit < 1):
            raise ValueError("Context limit must be a positive integer")
        torch, transformers = dependencies()
        self.torch = torch
        self.path = Path(model_path)
        load_kwargs = {'local_files_only': True, 'trust_remote_code': False}
        if device == 'cuda':
            load_kwargs['dtype'] = torch.bfloat16
        self.tokenizer = transformers.AutoTokenizer.from_pretrained(self.path, local_files_only=True, trust_remote_code=False)
        if (self.path / "adapter_config.json").exists():
            from peft import PeftModel
            recipe_path = self.path / "tiny_base_recipe.json"
            if recipe_path.exists():
                recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
                torch.manual_seed(recipe["seed"])
                base = transformers.GPT2LMHeadModel(transformers.GPT2Config.from_dict(recipe["config"]))
            else:
                adapter = json.loads((self.path / "adapter_config.json").read_text(encoding="utf-8"))
                base_path = adapter["base_model_name_or_path"]
                base = transformers.AutoModelForCausalLM.from_pretrained(base_path, **load_kwargs)
            self.model = PeftModel.from_pretrained(base, self.path, is_trainable=False)
        else:
            self.model = transformers.AutoModelForCausalLM.from_pretrained(self.path, **load_kwargs)
        self.model.to(device).eval()
        self.device, self.max_new_tokens, self.limit = device, max_new_tokens, token_budget
        self.owns_ledger = ledger is None
        self.ledger = TokenLedger(token_budget) if ledger is None else ledger
        text_config = getattr(self.model.config, "text_config", self.model.config)
        self.context = getattr(text_config, "max_position_embeddings", getattr(text_config, "n_positions", 2048))
        if context_limit is not None:
            self.context = min(self.context, context_limit)
        configured_eos = self.model.generation_config.eos_token_id
        self.eos_ids = list(dict.fromkeys(
            [i for i in [self.tokenizer.eos_token_id] +
             (list(configured_eos) if isinstance(configured_eos, (list, tuple)) else [configured_eos]) if i is not None]))
        self.reset()

    def reset(self):
        if self.owns_ledger:
            self.ledger.reset()
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
        self.generations = []

    def close(self):
        if hasattr(self, "model"):
            del self.model
        gc.collect()
        if self.device == "cuda":
            self.torch.cuda.empty_cache()

    def complete(self, prompt, role="model"):
        ids = prompt_ids(self.tokenizer, prompt)
        # Preserve the legacy mutable per-backend cap, including callers that
        # lower backend.limit between calls, while also enforcing shared limits.
        used = self.usage["prompt_tokens"] + self.usage["completion_tokens"]
        context = min(self.context, max(1, self.limit - used))
        ticket, allowance = self.ledger.begin(role, len(ids), self.max_new_tokens, context, digest(prompt))
        self.usage["prompt_tokens"] += len(ids)
        self.usage["calls"] += 1
        try:
            batch = self.torch.tensor([ids], device=self.device)
            with self.torch.no_grad():
                generated = self.model.generate(input_ids=batch, attention_mask=self.torch.ones_like(batch),
                    max_new_tokens=allowance, do_sample=False, pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.eos_ids or None)
            new_ids = generated[0, len(ids):].tolist()
            self.ledger.finish(ticket, len(new_ids))
        except Exception as exc:
            if ticket in self.ledger.pending:
                self.ledger.fail(ticket, type(exc).__name__)
            raise
        self.usage["completion_tokens"] += len(new_ids)
        result = {"text": self.tokenizer.decode(new_ids, skip_special_tokens=True),
                  "usage": {"prompt_tokens": len(ids), "completion_tokens": len(new_ids)}}
        self.generations.append({"prompt_hash": digest(prompt), **result})
        return result


def json_response(text):
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON response key")
            value[key] = item
        return value
    value = json.loads(text, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Model must return a JSON object")
    return value


class LanguageModelActor:
    def __init__(self, backend, envelope_mode="strict"):
        if envelope_mode not in {"strict", "extract"}:
            raise ValueError("Unknown actor envelope policy")
        self.backend = backend
        self.envelope_mode = envelope_mode

    def propose(self, task, state, phase, target=None, attempt=0):
        response_schema = {"type": "object", "required": ["actions", "done"], "additionalProperties": False,
            "properties": {"done": {"type": "boolean"}, "actions": {"type": "array", "maxItems": 16, "items": {"oneOf": [
                {"type": "object", "required": ["op", "ok"], "additionalProperties": False,
                 "properties": {"op": {"const": "validate"}, "ok": {"type": "boolean"}}},
                {"type": "object", "required": ["op", "path", "value"], "additionalProperties": False,
                 "properties": {"op": {"const": "write"}, "path": {"type": "string"}, "value": {}}},
                {"type": "object", "required": ["op", "path"], "additionalProperties": False,
                 "properties": {"op": {"const": "delete"}, "path": {"type": "string"}}}]}}}}
        prompt = ("Return one JSON object matching response_schema, with a top-level actions array even for one action. "
                  "Propose initial execution or a targeted repair using ordered tool actions. "
                  "Set done=false when waiting for a tool result; the next call includes the actual results in events. "
                  "Set done=true after proposing all required effects for this phase. A completion claim is checked independently. "
                  "The visible files contain the inputs. First validate the required fields using the tool; "
                  "then include required data and report writes when fields are present, or only the blocked report when missing. "
                  "When validation is already in events, use its actual result to continue. "
                  "Preserve input files and existing satisfied requirements.\n"
                  + canonical({"task": task, "files": state.files, "events": state.events,
                               "phase": phase, "repair_target": target, "attempt": attempt,
                               "response_schema": response_schema}) + "\nJSON:\n")
        output = self.backend.complete(prompt)
        try:
            value = json_response(output["text"])
        except (ValueError, TypeError) as exc:
            raise ValueError("Language model did not return a valid JSON action proposal") from exc
        if not isinstance(value.get("actions"), list):
            raise ValueError("Language model JSON is missing actions")
        strict_valid = set(value) == {"actions", "done"}
        if "done" not in value or type(value["done"]) is not bool or len(value["actions"]) > 16 \
                or (self.envelope_mode == "strict" and not strict_valid):
            raise ValueError("Action response must match the top-level schema")
        shapes = {"validate": {"op", "ok"}, "write": {"op", "path", "value"}, "delete": {"op", "path"}}
        for action in value["actions"]:
            if not isinstance(action, dict) or not isinstance(action.get("op"), str) or action["op"] not in shapes \
                    or set(action) != shapes[action["op"]]:
                raise ValueError("Tool action does not match the declared schema")
            if action["op"] == "validate" and type(action["ok"]) is not bool:
                raise ValueError("validate.ok must be boolean")
            if action["op"] != "validate" and not isinstance(action["path"], str):
                raise ValueError("Tool action path must be a string")
        json.dumps(value, allow_nan=False)
        return {"actions": value["actions"], "done": value["done"], "usage": output["usage"],
                "strict_interface_valid": strict_valid,
                "ignored_envelope_fields": sorted(set(value) - {"actions", "done"})}


class LanguageModelAnalyzer:
    """Invalid JSON or unsupported evidence abstains; it never silently passes."""

    def __init__(self, backend):
        self.backend = backend
        self.errors = []

    def __call__(self, task, state, events_visible=True):
        response = self.backend.complete(analysis_prompt(task, state, events_visible))
        indices = {e["index"] for e in state.events} if events_visible else set()
        try:
            rows = json_response(response["text"])["findings"]
            if not isinstance(rows, list) or len(rows) != len(REQUIREMENTS):
                raise ValueError("Need exactly four requirement findings")
            by_id = {}
            for item in rows:
                rid = item["id"]
                if rid not in REQUIREMENTS or rid in by_id or item["status"] not in {"satisfied", "violated", "unknown"}:
                    raise ValueError("Invalid or duplicate requirement judgment")
                evidence = item.get("evidence", [])
                if not isinstance(evidence, list) or any(type(i) is not int or i not in indices for i in evidence):
                    raise ValueError("Invented or hidden evidence reference")
                by_id[rid] = dict(item)
            # Preserve model judgments for evaluation. Hidden history cannot be
            # cited, but a visible snapshot may independently prove a violation.
            # Unconditional abstention here concealed both correct and unsafe
            # predictions; constraint enforcement belongs in the independent guard.
        except (ValueError, TypeError, KeyError) as exc:
            self.errors.append(str(exc))
            by_id = {rid: {"id": rid, "status": "unknown", "evidence": []} for rid in REQUIREMENTS}
        return [{"id": rid, "status": by_id[rid]["status"], "evidence": by_id[rid].get("evidence", []),
                 "hard": rid in {"R_INPUT", "R_ORDER"}, "reason": "language_model_judgment"} for rid in REQUIREMENTS]


class SchemaLanguageModelAnalyzer:
    """Full schema and snapshot references, adapted to the existing runner."""

    def __init__(self, backend):
        self.backend, self.errors = backend, []

    def __call__(self, task, state, events_visible=True):
        from .formal_data import formal_prompt, validate_findings
        from .formal_eval import parse_prediction
        from .requirements import extract_requirements
        requirements = task.get("requirements")
        if requirements is None:
            requirements = [{"id": row["id"], "quote": row["quote"], "hard": row["type"] == "hard"}
                            for row in extract_requirements(task["request"])]
        public = {"request": task["request"], "inputs": task["inputs"], "requirements": requirements,
                  "observation": {"files": state.files, "events": state.events if events_visible else None}}
        if isinstance(task.get("spec", {}).get("operation"), dict):
            public["execution_spec"] = task["spec"]
        response = self.backend.complete(formal_prompt(public))
        try:
            parsed = parse_prediction(response["text"], requirements)
            findings = validate_findings(list(parsed.values()), public)
        except (ValueError, KeyError, TypeError) as exc:
            self.errors.append(str(exc))
            findings = {row["id"]: {"status": "unknown", "evidence": []} for row in requirements}
        return [{"id": row["id"], "status": findings[row["id"]]["status"], "hard": row["hard"],
                 "evidence": findings[row["id"]]["evidence"], "reason": "schema_language_model_judgment"}
                for row in requirements]
