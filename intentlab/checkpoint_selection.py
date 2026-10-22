"""Prove exported trainable tensors match the validation-selected checkpoint."""

import hashlib
import json
import math
from pathlib import Path

from .core import canonical


def best_validation(history):
    if not isinstance(history, list) or not history:
        raise ValueError("No validation observations for checkpoint selection")
    points, previous = [], 0
    for row in history:
        step, validation = row.get("step"), row.get("validation")
        if type(step) is not int or step <= previous or not isinstance(validation, dict):
            raise ValueError("Validation history must have strictly increasing update steps")
        loss, tokens = validation.get("loss"), validation.get("target_tokens")
        if type(loss) not in {int, float} or not math.isfinite(loss) or loss < 0 or type(tokens) is not int or tokens < 1:
            raise ValueError("Finite token-weighted validation loss and positive target count required")
        points.append({"step": step, "validation_loss": loss, "validation_target_tokens": tokens})
        previous = step
    if len({point["validation_target_tokens"] for point in points}) != 1:
        raise ValueError("Validation target population changed during checkpoint selection")
    return min(points, key=lambda row: row["validation_loss"])  # Stable first tie, matching the trainer's strict <.


def tensor_hash(weights):
    import torch
    if not isinstance(weights, dict) or not weights:
        raise ValueError("Nonempty trainable state required")
    result = hashlib.sha256()
    for name, value in sorted(weights.items()):
        tensor = value.detach().cpu().contiguous()
        if not bool(torch.isfinite(tensor).all()):
            raise ValueError("Non-finite selected parameter")
        header = canonical({"name": name, "dtype": str(tensor.dtype), "shape": list(tensor.shape)}).encode()
        raw = tensor.reshape(-1).view(torch.uint8).numpy().tobytes()
        result.update(len(header).to_bytes(8, "big") + header + len(raw).to_bytes(8, "big") + raw)
    return result.hexdigest()


def exported_tensor_name(name, mode):
    if mode == "full":
        return name
    if mode not in {"lora", "qlora"}:
        raise ValueError("Unknown export mode")
    for module in ("lora_A", "lora_B", "lora_embedding_A", "lora_embedding_B"):
        needle = "." + module + ".default."
        if needle in name:
            return name.replace(needle, "." + module + ".", 1)
    raise ValueError("Unsupported trainable adapter parameter: " + name)


def selection_proof(history, weights, model_dir, mode):
    import torch
    from safetensors import safe_open
    point = best_validation(history)
    parameter_hash = tensor_hash(weights)
    model_dir = Path(model_dir)
    files = sorted(model_dir.glob("*.safetensors"))
    if not files:
        raise ValueError("Exported safe tensor weights missing")
    expected = {exported_tensor_name(name, mode): tensor for name, tensor in weights.items()}
    if len(expected) != len(weights):
        raise ValueError("Colliding exported parameter names")
    found = set()
    file_hashes = {}
    for path in files:
        sha = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sha.update(chunk)
        file_hashes[path.name] = sha.hexdigest()
        with safe_open(path, framework="pt", device="cpu") as handle:
            for name in handle.keys():
                if name in found:
                    raise ValueError("Duplicate tensor across export shards")
                found.add(name)
                if name in expected:
                    actual, selected = handle.get_tensor(name), expected[name].detach().cpu()
                    if actual.dtype != selected.dtype or actual.shape != selected.shape or not torch.equal(actual, selected):
                        raise ValueError("Export does not contain the validation-selected tensor: " + name)
    if not set(expected) <= found or (mode != "full" and set(expected) != found):
        raise ValueError("Exported trainable parameter coverage differs")
    return {"rule": "minimum_validation_loss_first_tie", **point,
            "trainable_tensor_sha256": parameter_hash, "trainable_tensor_count": len(weights),
            "export_files_sha256": file_hashes}


def verify_selected_checkpoint(directory, result):
    import torch
    directory = Path(directory)
    if "selection" not in result or not result.get("completed"):
        raise ValueError("Training result lacks an explicit checkpoint selection proof")
    saved = torch.load(directory / "latest.pt", map_location="cpu", weights_only=True)
    for field in ("config", "history", "data_hash", "base_identity"):
        if canonical(saved[field]) != canonical(result[field]):
            raise ValueError("Checkpoint/result provenance differs: " + field)
    best = best_validation(saved["history"])
    if saved["step"] != result["config"]["steps"] or saved.get("best_step") != best["step"] or saved["best_loss"] != best["validation_loss"]:
        raise ValueError("Checkpoint position or selected validation minimum differs")
    proof = selection_proof(saved["history"], saved["best_weights"], directory / "model", result["config"]["mode"])
    recorded = json.loads((directory / "model/selection.json").read_text(encoding="utf-8"))
    if canonical(proof) != canonical(result["selection"]) or canonical(proof) != canonical(recorded):
        raise ValueError("Saved checkpoint selection proof differs")
    return proof
