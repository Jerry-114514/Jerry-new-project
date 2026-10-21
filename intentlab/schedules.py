"""Framework-independent LR control; events and state are serializable."""

import math
from dataclasses import asdict, dataclass


@dataclass
class Plateau:
    lr: float
    factor: float = 0.5
    patience: int = 2
    threshold: float = 0.001
    cooldown: int = 1
    min_lr: float = 0.000005
    best: float | None = None
    bad: int = 0
    remaining: int = 0

    def __post_init__(self):
        if not 0 < self.factor < 1 or self.lr <= 0 or not 0 < self.min_lr <= self.lr:
            raise ValueError("Invalid LR bounds or factor")
        if self.patience < 0 or self.cooldown < 0 or not 0 <= self.threshold < 1:
            raise ValueError("Invalid plateau window")

    def step(self, loss):
        if not math.isfinite(loss) or loss < 0:
            raise ValueError("Validation loss must be finite and nonnegative")
        old = self.lr
        if self.best is None or loss < self.best * (1 - self.threshold):
            self.best, self.bad = loss, 0
        else:
            self.bad += 1
        if self.remaining:
            self.remaining -= 1
            self.bad = 0
        if self.bad > self.patience:
            self.lr = max(self.min_lr, self.lr * self.factor)
            self.bad, self.remaining = 0, self.cooldown
        return {"old_lr": old, "new_lr": self.lr, "reduced": self.lr < old, **asdict(self)}


def warmup_cosine(step, total, peak, minimum, warmup):
    if total <= 0 or not 0 <= warmup < total or not 0 < minimum <= peak:
        raise ValueError("Invalid schedule")
    if step < warmup:
        return peak * (step + 1) / warmup
    progress = min(1.0, (step - warmup) / max(1, total - warmup - 1))
    return minimum + 0.5 * (peak - minimum) * (1 + math.cos(math.pi * progress))
