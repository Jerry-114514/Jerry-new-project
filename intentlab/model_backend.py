"""Local Hugging Face generation, strict JSON interfaces and bounded token use."""

import json
from pathlib import Path

from .analysis import REQUIREMENTS
from .core import canonical, digest
from .neural import dependencies
from .sft_data import analysis_prompt
from .prompts import prompt_ids


class BudgetExceeded(ValueError):
    pass


class LocalBackend:
    def __init__(self, model_path, device="cpu", max_new_tokens=256, token_budget=20000):
        if max_new_tokens < 1 or token_budget < 1:
            raise ValueError("Positive generation and token budgets required")
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
        self.context = getattr(self.model.config, "max_position_embeddings", getattr(self.model.config, "n_positions", 2048))
        configured_eos = self.model.generation_config.eos_token_id
        self.eos_ids = list(dict.fromkeys(
            [i for i in [self.tokenizer.eos_token_id] +
             (list(configured_eos) if isinstance(configured_eos, (list, tuple)) else [configured_eos]) if i is not None]))
        self.reset()

    def reset(self):
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
        self.generations = []

    def complete(self, prompt):
        ids = prompt_ids(self.tokenizer, prompt)
        used = self.usage["prompt_tokens"] + self.usage["completion_tokens"]
        allowance = min(self.max_new_tokens, self.limit - used - len(ids), self.context - len(ids))
        if allowance < 1:
            raise BudgetExceeded("Prompt exceeds remaining token budget or model context")
        batch = self.torch.tensor([ids], device=self.device)
        self.usage["prompt_tokens"] += len(ids)
        self.usage["calls"] += 1
        with self.torch.no_grad():
            generated = self.model.generate(input_ids=batch, attention_mask=self.torch.ones_like(batch),
                max_new_tokens=allowance, do_sample=False, pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.eos_ids or None)
        new_ids = generated[0, len(ids):].tolist()
        self.usage["completion_tokens"] += len(new_ids)
        result = {"text": self.tokenizer.decode(new_ids, skip_special_tokens=True),
                  "usage": {"prompt_tokens": len(ids), "completion_tokens": len(new_ids)}}
        self.generations.append({"prompt_hash": digest(prompt), **result})
        return result


def json_response(text):
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Model must return a JSON object")
    return value


class LanguageModelActor:
    def __init__(self, backend):
        self.backend = backend

    def propose(self, task, state, phase, target=None, attempt=0):
        prompt = ("Return only a JSON object containing actions. Allowed actions: "
                  "{op:validate,ok:true}, {op:write,path:relative_path,value:JSON}, {op:delete,path:relative_path}. "
                  "First validate fields using the tool. Preserve input files and existing satisfied requirements.\n"
                  + canonical({"task": task, "files": state.files, "events": state.events,
                               "phase": phase, "repair_target": target, "attempt": attempt}) + "\nJSON:\n")
        output = self.backend.complete(prompt)
        try:
            value = json_response(output["text"])
        except (ValueError, TypeError) as exc:
            raise ValueError("Language model did not return a valid JSON action proposal") from exc
        if not isinstance(value.get("actions"), list):
            raise ValueError("Language model JSON is missing actions")
        return {"actions": value["actions"], "usage": output["usage"]}


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
