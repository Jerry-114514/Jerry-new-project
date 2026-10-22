"""One task token ledger shared by execution and analysis model calls."""

from copy import deepcopy
import time


class BudgetExceeded(ValueError):
    pass


class TokenLedger:
    def __init__(self, limit):
        if type(limit) is not int or limit < 1:
            raise ValueError("Token limit must be a positive integer")
        self.limit = limit
        self.reset()

    def reset(self):
        if getattr(self, "pending", {}):
            raise RuntimeError("Cannot reset a ledger with active calls")
        self.events = []
        self.pending = {}
        self.charged = 0

    @property
    def remaining(self):
        return self.limit - self.charged - sum(row["reserved"] for row in self.pending.values())

    def begin(self, role, prompt_tokens, maximum, context, prompt_hash):
        if not isinstance(role, str) or not role or any(type(v) is not int or v < 1
                                                       for v in (prompt_tokens, maximum, context)):
            raise ValueError("Role and positive integer token counts required")
        allowance = min(maximum, self.remaining - prompt_tokens, context - prompt_tokens)
        if allowance < 1:
            self.events.append({"role": role, "status": "denied", "prompt_hash": prompt_hash,
                                "prompt_tokens": prompt_tokens, "charged_tokens": 0,
                                "reason": "context_or_shared_budget_exhausted"})
            raise BudgetExceeded("Prompt exceeds shared task budget or model context")
        ticket = len(self.events)
        event = {"role": role, "status": "active", "prompt_hash": prompt_hash,
                 "prompt_tokens": prompt_tokens, "completion_allowance": allowance}
        self.events.append(event)
        self.pending[ticket] = {"reserved": prompt_tokens + allowance, "start": time.perf_counter()}
        return ticket, allowance

    def finish(self, ticket, completion_tokens):
        event = self.events[ticket]
        if ticket not in self.pending:
            raise ValueError("Unknown or settled reservation")
        if type(completion_tokens) is not int or not 0 <= completion_tokens <= event["completion_allowance"]:
            self.fail(ticket, "invalid_completion_usage")
            raise ValueError("Completion exceeds reserved allowance or has invalid usage")
        reservation = self.pending.pop(ticket)
        charged = event["prompt_tokens"] + completion_tokens
        self.charged += charged
        event.update(status="completed", completion_tokens=completion_tokens,
                     charged_tokens=charged, elapsed_seconds=time.perf_counter() - reservation["start"])

    def fail(self, ticket, reason):
        if ticket not in self.pending:
            raise ValueError("Unknown or settled reservation")
        reservation = self.pending.pop(ticket)
        self.charged += reservation["reserved"]
        self.events[ticket].update(status="error", completion_tokens=None,
            charged_tokens=reservation["reserved"], reason=reason,
            elapsed_seconds=time.perf_counter() - reservation["start"])

    def snapshot(self):
        return {"limit": self.limit, "charged_tokens": self.charged,
            "remaining_tokens": self.remaining, "calls": sum(row["status"] != "denied" for row in self.events),
            "denied_calls": sum(row["status"] == "denied" for row in self.events),
            "known_prompt_tokens": sum(row["prompt_tokens"] for row in self.events if row["status"] != "denied"),
            "known_completion_tokens": sum(row.get("completion_tokens") or 0 for row in self.events),
            "failed_reservations": sum(row["status"] == "error" for row in self.events),
            "failure_accounting": "Unknown failed generation length conservatively charges its full reservation",
            "events": deepcopy(self.events)}
