"""Causal-LM SFT with masked targets, LoRA/QLoRA and resumable optimizer state.

Heavy dependencies are optional. `--model tiny` builds a real small GPT-2 locally;
it exercises the same training loop without downloading pretrained weights.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import random
import sys
import time

from .core import digest
from .report import save_json
from .schedules import Plateau, warmup_cosine
from .sft_data import read_pairs, validate_splits
from .prompts import prompt_ids


def dependencies():
    try:
        import torch
        import transformers
        return torch, transformers
    except ImportError as exc:
        raise RuntimeError("Install the optional ML requirements; see docs/neural-training.md") from exc


def tokenizer_for_tiny(rows):
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
    from transformers import PreTrainedTokenizerFast
    raw = Tokenizer(models.BPE(unk_token="[UNK]"))
    raw.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    raw.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(vocab_size=768, special_tokens=["[PAD]", "[BOS]", "[EOS]", "[UNK]"],
                                 initial_alphabet=pre_tokenizers.ByteLevel.alphabet())
    # Tokenizer learns only training text, never validation/test vocabulary statistics.
    raw.train_from_iterator((r["prompt"] + r["completion"] for r in rows), trainer)
    return PreTrainedTokenizerFast(tokenizer_object=raw, pad_token="[PAD]", bos_token="[BOS]",
                                  eos_token="[EOS]", unk_token="[UNK]")


def encode_pair(tokenizer, row, max_length):
    prompt = prompt_ids(tokenizer, row["prompt"])
    completion = tokenizer.encode(row["completion"], add_special_tokens=False)
    if tokenizer.eos_token_id is not None:
        completion.append(tokenizer.eos_token_id)
    if not prompt or not completion or len(prompt) + len(completion) > max_length:
        raise ValueError(f"Sample {row['task_id']} empty or exceeds max_length; no silent truncation")
    return {"input_ids": prompt + completion, "labels": [-100] * len(prompt) + completion}


def batch_tensors(examples, pad_id, device):
    torch, _ = dependencies()
    length = max(len(x["input_ids"]) for x in examples)
    ids, labels, masks = [], [], []
    for item in examples:
        padding = length - len(item["input_ids"])
        ids.append(item["input_ids"] + [pad_id] * padding)
        labels.append(item["labels"] + [-100] * padding)
        masks.append([1] * len(item["input_ids"]) + [0] * padding)
    return {"input_ids": torch.tensor(ids, device=device), "labels": torch.tensor(labels, device=device),
            "attention_mask": torch.tensor(masks, device=device)}


def token_loss(model, batch):
    torch, _ = dependencies()
    precision = (torch.autocast('cuda', dtype=torch.bfloat16)
                 if batch['input_ids'].device.type == 'cuda' else nullcontext())
    with precision:
        output = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"], use_cache=False)
    labels = batch["labels"][:, 1:].contiguous()
    count = int((labels != -100).sum().item())
    if not count:
        raise ValueError("Batch contains no supervised targets")
    loss = torch.nn.functional.cross_entropy(output.logits[:, :-1].float().reshape(-1, output.logits.shape[-1]),
                                             labels.reshape(-1), ignore_index=-100, reduction="sum")
    return loss, count


def evaluate_loss(model, examples, tokenizer, device, batch_size=2):
    torch, _ = dependencies()
    model.eval()
    total, tokens = 0.0, 0
    with torch.no_grad():
        for start in range(0, len(examples), batch_size):
            batch = batch_tensors(examples[start:start + batch_size], tokenizer.pad_token_id, device)
            loss, count = token_loss(model, batch)
            total += float(loss.item())
            tokens += count
    if not tokens:
        raise ValueError("Empty evaluation targets")
    return {"loss": total / tokens, "target_tokens": tokens}


def trainable_state(model):
    return {name: param.detach().cpu().clone() for name, param in model.named_parameters() if param.requires_grad}


def restore_trainable(model, state):
    names = {name for name, param in model.named_parameters() if param.requires_grad}
    if names != set(state):
        raise ValueError("Checkpoint trainable-parameter schema mismatch")
    model.load_state_dict(state, strict=False)


def local_model_fingerprint(path):
    """Include the actual base tensors, not just a mutable local directory name."""
    root = Path(path)
    files = sorted(p for p in root.iterdir() if p.is_file() and
                   (p.suffix in {".safetensors", ".bin"} or p.name == "config.json"))
    if not files:
        raise ValueError("No pretrained base-model files found")
    value = hashlib.sha256()
    for path in files:
        value.update(path.name.encode())
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                value.update(chunk)
    return value.hexdigest()


def train_neural(config, out, stop_after=None, resume=None):
    torch, transformers = dependencies()
    if config["mode"] not in {"full", "lora", "qlora"} or config["schedule"] not in {"cosine", "plateau"} or config["device"] not in {"cpu", "cuda"}:
        raise ValueError("Unsupported training mode, schedule or device")
    if config["steps"] < 2 or config["eval_every"] < 1 or config["batch_size"] < 1 or config["accumulation"] < 1:
        raise ValueError("Positive steps, batch and evaluation configuration required")
    device = config["device"]
    if device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA unavailable; use CPU smoke or install a CUDA-enabled PyTorch")
    if config["mode"] == "qlora" and device != "cuda":
        raise ValueError("QLoRA requires a supported CUDA GPU in this implementation")
    if config["mode"] == "qlora" and config["model"] == "tiny":
        raise ValueError("QLoRA requires a supported pretrained model, not the tiny smoke model")
    if config["limit"] < 0 or config["threads"] < 1 or config["max_length"] < 8:
        raise ValueError("Invalid example limit, CPU thread count or context size")
    if not all(math.isfinite(config[k]) for k in ("lr", "minimum_lr")) or not 0 < config["minimum_lr"] <= config["lr"]:
        raise ValueError("Invalid learning-rate bounds")
    config_file = out / "run_config.json"
    if config_file.exists() and json.loads(config_file.read_text(encoding="utf-8")) != config:
        raise ValueError("Output directory belongs to another configuration; choose a new --out")
    random.seed(config["seed"])
    torch.manual_seed(config["seed"])
    torch.set_num_threads(config.get("threads", 2))
    split_names = ("train", "validation") if config.get("defer_test", False) else ("train", "validation", "test")
    splits = {split: read_pairs(Path(config["data"]) / f"{split}.jsonl") for split in split_names}
    validate_splits(splits)
    fingerprint = digest(splits)
    if config.get("limit"):
        splits = {k: v[:config["limit"]] for k, v in splits.items()}
    if config["model"] == "tiny":
        tokenizer = tokenizer_for_tiny(splits["train"])
        model = transformers.GPT2LMHeadModel(transformers.GPT2Config(
            vocab_size=len(tokenizer), n_positions=config["max_length"], n_layer=2, n_head=2, n_embd=48,
            bos_token_id=tokenizer.bos_token_id, eos_token_id=tokenizer.eos_token_id, pad_token_id=tokenizer.pad_token_id,
            attn_pdrop=0.1, resid_pdrop=0.1, embd_pdrop=0.1))
        model.to(device)
    else:
        if not Path(config["model"]).is_dir() and not config.get("revision"):
            raise ValueError("Pin --revision for a remote model, or use a local pretrained directory")
        tokenizer = transformers.AutoTokenizer.from_pretrained(config["model"], revision=config.get("revision"),
            cache_dir=out / "download-cache", trust_remote_code=False)
        if tokenizer.pad_token_id is None:
            if tokenizer.eos_token_id is None:
                raise ValueError("Tokenizer needs pad or EOS token")
            tokenizer.pad_token = tokenizer.eos_token
        kwargs = {"revision": config.get("revision"), "trust_remote_code": False,
                  "cache_dir": out / "download-cache", "dtype": torch.bfloat16 if device == "cuda" else torch.float32}
        if config["mode"] == "qlora":
            kwargs["quantization_config"] = transformers.BitsAndBytesConfig(load_in_4bit=True,
                bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
            kwargs["device_map"] = {"": device}
        model = transformers.AutoModelForCausalLM.from_pretrained(config["model"], **kwargs)
        if config["mode"] != "qlora":
            model.to(device)
    if config["model"] == "tiny":
        identity = digest({"config": model.config.to_dict(), "vocab": tokenizer.get_vocab(), "seed": config["seed"]})
    elif Path(config["model"]).is_dir():
        identity = local_model_fingerprint(config["model"])
    else:
        identity = digest({"model": config["model"], "revision": config["revision"],
                           "resolved_commit": getattr(model.config, "_commit_hash", None)})
    if config["mode"] in {"lora", "qlora"}:
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        if config["mode"] == "qlora":
            model = prepare_model_for_kbit_training(model)
        model = get_peft_model(model, LoraConfig(r=config["rank"], lora_alpha=config["alpha"],
            lora_dropout=0.0, target_modules="all-linear", task_type="CAUSAL_LM",
            fan_in_fan_out=model.config.model_type == "gpt2"))
    if device == 'cuda':
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
    encoded = {split: [encode_pair(tokenizer, row, config["max_length"]) for row in rows] for split, rows in splits.items()}
    parameters = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=config["lr"])
    scheduler = Plateau(config["lr"], min_lr=config["minimum_lr"])
    start, history, best_loss, best_weights = 0, [], float("inf"), None
    used_tokens = 0
    if resume:
        saved = torch.load(resume, map_location="cpu", weights_only=True)
        if saved["config"] != config or saved["data_hash"] != fingerprint or saved["base_identity"] != identity:
            raise ValueError("Resume requires identical configuration and dataset")
        restore_trainable(model, saved["weights"])
        optimizer.load_state_dict(saved["optimizer"])
        scheduler = Plateau(**saved["scheduler"])
        start, history = saved["step"], saved["history"]
        best_loss, best_weights = saved["best_loss"], saved["best_weights"]
        used_tokens = saved["used_tokens"]
        random.setstate(saved["python_rng"])
        torch.set_rng_state(saved["torch_rng"])
        if device == "cuda":
            torch.cuda.set_rng_state_all(saved["cuda_rng"])
    out.mkdir(parents=True, exist_ok=True)
    save_json(config_file, config)
    warmup = max(1, int(config["steps"] * 0.05))
    end = min(config["steps"], stop_after) if stop_after is not None else config["steps"]
    if not start < end <= config["steps"]:
        raise ValueError("Stop/resume step must advance training within its original horizon")
    started = time.perf_counter()
    n = len(encoded["train"])
    examples_per_step = config["batch_size"] * config["accumulation"]
    for step in range(start, end):
        indices = []
        for offset in range(examples_per_step):
            absolute = step * examples_per_step + offset
            epoch, position = divmod(absolute, n)
            order = list(range(n))
            random.Random(config["seed"] + epoch).shuffle(order)
            indices.append(order[position])
        micros = [indices[i:i + config["batch_size"]] for i in range(0, len(indices), config["batch_size"])]
        total_targets = sum(sum(label != -100 for label in encoded["train"][i]["labels"][1:]) for i in indices)
        lr = (warmup_cosine(step, config["steps"], config["lr"], config["minimum_lr"], warmup)
              if config["schedule"] == "cosine" else config["lr"] * (step + 1) / warmup if step < warmup else scheduler.lr)
        for group in optimizer.param_groups:
            group["lr"] = lr
        optimizer.zero_grad(set_to_none=True)
        model.train()
        train_sum = 0.0
        for micro in micros:
            items = [encoded["train"][i] for i in micro]
            loss, _ = token_loss(model, batch_tensors(items, tokenizer.pad_token_id, device))
            if not torch.isfinite(loss):
                raise ValueError("Non-finite training loss; refusing optimizer update")
            (loss / total_targets).backward()
            train_sum += float(loss.detach().item())
            used_tokens += sum(len(item["input_ids"]) for item in items)
        grad_norm = torch.nn.utils.clip_grad_norm_(parameters, 1.0, error_if_nonfinite=True)
        optimizer.step()
        if (step + 1) % config["eval_every"] == 0 or step + 1 == config["steps"]:
            validation = evaluate_loss(model, encoded["validation"], tokenizer, device, config["batch_size"])
            event = scheduler.step(validation["loss"]) if config["schedule"] == "plateau" and step + 1 >= warmup else None
            if validation["loss"] < best_loss:
                best_loss, best_weights = validation["loss"], trainable_state(model)
            history.append({"step": step + 1, "train_loss": train_sum / total_targets,
                            "validation": validation, "lr_used": lr, "gradient_norm": float(grad_norm), "scheduler": event})
            if device == 'cuda':
                torch.cuda.synchronize()
            print(json.dumps({'step': step + 1, 'validation_loss': validation['loss'],
                              'lr': lr, 'elapsed_seconds': time.perf_counter() - started}), flush=True)
        checkpoint = {"config": config, "data_hash": fingerprint, "base_identity": identity, "step": step + 1,
            "weights": trainable_state(model), "optimizer": optimizer.state_dict(), "scheduler": asdict(scheduler),
            "history": history, "best_loss": best_loss, "best_weights": best_weights, "used_tokens": used_tokens,
            "python_rng": random.getstate(), "torch_rng": torch.get_rng_state(),
            "cuda_rng": torch.cuda.get_rng_state_all() if device == "cuda" else []}
        # Atomic replacement prevents a failed save from destroying the last good checkpoint.
        temporary = out / "latest.tmp"
        torch.save(checkpoint, temporary)
        temporary.replace(out / "latest.pt")
    result = {"kind": "causal_lm_sft", "completed": end == config["steps"], "config": config,
        "data_hash": fingerprint, "base_identity": identity, "step": end, "history": history, "train_tokens": used_tokens,
        "parameters": sum(p.numel() for p in model.parameters()), "trainable_parameters": sum(p.numel() for p in parameters),
        "seconds_this_invocation": time.perf_counter() - started,
        "versions": {name: importlib.metadata.version(name) for name in ("torch", "transformers")}}
    if device == 'cuda':
        result['gpu'] = torch.cuda.get_device_name()
        result['peak_allocated_bytes'] = torch.cuda.max_memory_allocated()
        result['peak_reserved_bytes'] = torch.cuda.max_memory_reserved()
    if end == config["steps"]:
        if best_weights is None:
            raise ValueError("No evaluated checkpoint")
        restore_trainable(model, best_weights)
        if config.get("defer_test", False):
            result["test_deferred"] = True
        else:
            result["test"] = evaluate_loss(model, encoded["test"], tokenizer, device, config["batch_size"])
        model.save_pretrained(out / "model", safe_serialization=True)
        tokenizer.save_pretrained(out / "model")
        if config["mode"] in {"lora", "qlora"}:
            (out / "model/README.md").write_text(
                "# Intent Lab adapter artifact\n\n"
                f"Mode: {config['mode']}. Seed: {config['seed']}. Planned updates: {config['steps']}.\n\n"
                "The exported adapter is selected using validation loss. See ../result.json for provenance.\n"
                "A tiny model is randomly initialized for infrastructure testing; it is not a useful pretrained model.\n"
                "For the tiny adapter, tiny_base_recipe.json reconstructs its seeded base. Other adapters require their original base weights.\n",
                encoding="utf-8")
        # For tiny LoRA, save the seeded base so inference needs no external download.
        if config["model"] == "tiny" and config["mode"] == "lora":
            base = model.get_base_model()
            # Base tensors with LoRA wrappers are not a standalone base model: inference rebuilds by seed.
            save_json(out / "model" / "tiny_base_recipe.json", {"seed": config["seed"], "config": base.config.to_dict()})
    save_json(out / "result.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="JSON configuration; explicit CLI flags override it")
    parser.add_argument("--data", default="data/sft")
    parser.add_argument("--out", type=Path, default=Path("runs/neural"))
    parser.add_argument("--model", default="tiny")
    parser.add_argument("--revision")
    parser.add_argument("--mode", choices=["full", "lora", "qlora"], default="full")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--schedule", choices=["cosine", "plateau"], default="cosine")
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--eval-every", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--accumulation", type=int, default=2)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--lr", type=float, default=0.0005)
    parser.add_argument("--minimum-lr", type=float, default=0.000005)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--alpha", type=int, default=16)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--limit", type=int, default=8, help="0 uses all examples; default is smoke-only")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--defer-test", action="store_true",
                        help="Do not open or evaluate test data; required during formal development/training")
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--resume", type=Path)
    raw_args = sys.argv[1:] if argv is None else argv
    args = vars(parser.parse_args(raw_args))
    config_path = args.pop("config")
    out, stop_after, resume = args.pop("out"), args.pop("stop_after"), args.pop("resume")
    if config_path:
        supplied = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(supplied, dict) or set(supplied) - set(args):
            parser.error("Unknown JSON training configuration keys")
        explicit = {token.split("=")[0] for token in raw_args if token.startswith("--")}
        args = {key: value if "--" + key.replace("_", "-") in explicit else supplied.get(key, value)
                for key, value in args.items()}
    result = train_neural(args, out, stop_after, resume)
    print(json.dumps({k: v for k, v in result.items() if k != "history"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
