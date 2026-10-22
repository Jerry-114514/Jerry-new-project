"""Actual CPU logistic training; a pipeline smoke baseline, not LLM fine-tuning."""

from dataclasses import asdict
import json
import math
import random

from .schedules import Plateau, warmup_cosine


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-40.0, min(40.0, x))))


def predict(weights, features):
    return sigmoid(weights[0] + sum(w * x for w, x in zip(weights[1:], features)))


def metrics(weights, examples):
    if not examples:
        raise ValueError("Empty evaluation split")
    loss = 0.0
    tp = fp = fn = tn = 0
    for x, y in examples:
        p = max(1e-12, min(1 - 1e-12, predict(weights, x)))
        loss -= y * math.log(p) + (1 - y) * math.log(1 - p)
        pred = p >= 0.5
        tp += int(pred and y == 1)
        fp += int(pred and y == 0)
        fn += int(not pred and y == 1)
        tn += int(not pred and y == 0)
    return {"loss": loss / len(examples), "accuracy": (tp + tn) / len(examples),
            "false_positive": fp, "false_negative": fn, "n": len(examples)}


def read_examples(path):
    splits = {k: [] for k in ("train", "validation", "test")}
    group_splits = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        split = item["split"]
        task_id = item["task_id"]
        if task_id in group_splits and group_splits[task_id] != split:
            raise ValueError("Task leaked across splits")
        group_splits[task_id] = split
        for finding in item["findings"]:
            splits[split].append((finding["features"], item["labels"][finding["id"]]))
    if any(not value for value in splits.values()):
        raise ValueError("All three splits must be nonempty")
    return splits


def train(examples, schedule="plateau", seed=0, epochs=24, peak=0.15):
    if schedule not in {"cosine", "plateau"} or epochs < 3 or peak <= 0:
        raise ValueError("Invalid training configuration")
    rng = random.Random(seed)
    weights = [0.0] * (len(examples["train"][0][0]) + 1)
    # Linear baseline has a different LR scale than QLoRA; do not transfer these values.
    steps_per_epoch = math.ceil(len(examples["train"]) / 32)
    total = epochs * steps_per_epoch
    warmup = max(1, int(total * 0.05))
    minimum = peak / 20
    controller = Plateau(peak, min_lr=minimum)
    history = []
    best_loss, best_weights = float("inf"), None
    step = 0
    for epoch in range(epochs):
        order = list(examples["train"])
        rng.shuffle(order)
        for start in range(0, len(order), 32):
            batch = order[start:start + 32]
            lr = (warmup_cosine(step, total, peak, minimum, warmup) if schedule == "cosine"
                  else peak * (step + 1) / warmup if step < warmup else controller.lr)
            gradient = [0.0] * len(weights)
            for x, y in batch:
                error = predict(weights, x) - y
                gradient[0] += error
                for i, value in enumerate(x, 1):
                    gradient[i] += error * value
            weights = [w - lr * g / len(batch) for w, g in zip(weights, gradient)]
            step += 1
        validation = metrics(weights, examples["validation"])
        event = controller.step(validation["loss"]) if schedule == "plateau" and step >= warmup else None
        if validation["loss"] < best_loss:
            best_loss, best_weights = validation["loss"], weights[:]
        history.append({"epoch": epoch + 1, "step": step, "lr_used": lr,
                        "train": metrics(weights, examples["train"]), "validation": validation, "scheduler": event})
    # Test is evaluated once, after checkpoint selection by validation loss.
    return {"model_type": "logistic_rule_signal_smoke_baseline", "schedule": schedule, "seed": seed,
            "weights": best_weights, "best_validation_loss": best_loss,
            "test": metrics(best_weights, examples["test"]), "history": history,
            "lr_reductions": sum(bool(h["scheduler"] and h["scheduler"]["reduced"]) for h in history),
            "scheduler_state": asdict(controller), "epochs": epochs,
            "warning": "Engineered rule features and synthetic fixtures; not an LLM result or novelty claim."}
