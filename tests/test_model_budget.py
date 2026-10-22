import unittest
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from intentlab.budget import BudgetExceeded, TokenLedger
from intentlab.model_pool import LocalModelPool
from intentlab.cli import main
from intentlab.fixtures import build_tasks


class CountedBackend:
    """Controlled token producer for shared-ledger tests; never claims model efficacy."""
    active = 0
    maximum_active = 0

    def __init__(self, path, device, maximum, limit, ledger):
        self.path, self.ledger = path, ledger
        self.generations = []
        CountedBackend.active += 1
        CountedBackend.maximum_active = max(CountedBackend.maximum_active, CountedBackend.active)

    def reset(self):
        self.generations = []

    def close(self):
        CountedBackend.active -= 1

    def complete(self, prompt, role):
        ticket, allowance = self.ledger.begin(role, 4, 3, 100, "controlled")
        count = min(2, allowance)
        self.ledger.finish(ticket, count)
        reply = {"text": self.path, "usage": {"prompt_tokens": 4, "completion_tokens": count}}
        self.generations.append(reply)
        return reply


class BudgetTests(unittest.TestCase):
    def test_actor_and_analyzer_reservations_share_a_hard_cap(self):
        ledger = TokenLedger(15)
        first, allowance = ledger.begin("actor", 5, 7, 100, "a")
        self.assertEqual(allowance, 7)
        with self.assertRaises(BudgetExceeded):
            ledger.begin("analyzer", 3, 7, 100, "b")
        ledger.finish(first, 2)
        second, allowance = ledger.begin("analyzer", 4, 8, 100, "b")
        self.assertEqual(allowance, 4)
        ledger.finish(second, 4)
        self.assertEqual(ledger.remaining, 0)
        self.assertEqual(ledger.snapshot()["charged_tokens"], 15)

    def test_failed_generation_is_not_a_free_retry_or_reported_as_known_tokens(self):
        ledger = TokenLedger(12)
        ticket, _ = ledger.begin("actor", 4, 8, 100, "a")
        ledger.fail(ticket, "RuntimeError")
        snapshot = ledger.snapshot()
        self.assertEqual(snapshot["charged_tokens"], 12)
        self.assertEqual(snapshot["known_completion_tokens"], 0)
        self.assertIsNone(snapshot["events"][0]["completion_tokens"])
        with self.assertRaises(BudgetExceeded):
            ledger.begin("analyzer", 1, 1, 100, "b")

    def test_reservations_cannot_be_reset_or_settled_twice(self):
        ledger = TokenLedger(12)
        ticket, _ = ledger.begin("actor", 4, 8, 100, "a")
        with self.assertRaises(RuntimeError):
            ledger.reset()
        with self.assertRaises(ValueError):
            ledger.finish(ticket, 9)
        self.assertEqual(ledger.remaining, 0)
        with self.assertRaises(ValueError):
            ledger.finish(ticket, 1)

    def test_role_switches_keep_budget_and_never_keep_two_models_resident(self):
        CountedBackend.active = CountedBackend.maximum_active = 0
        pool = LocalModelPool({"actor": "fixed-actor", "analyzer": "adapter"},
                              token_budget=15, factory=CountedBackend)
        try:
            pool.role("actor").complete("initial")
            pool.role("analyzer").complete("inspect")
            with self.assertRaises(BudgetExceeded):
                pool.role("actor").complete("repair")
            self.assertEqual(CountedBackend.maximum_active, 1)
            self.assertEqual(pool.ledger.snapshot()["charged_tokens"], 12)
            self.assertEqual(len(pool.generations), 2)
            pool.reset()
            self.assertEqual(pool.ledger.remaining, 15)
        finally:
            pool.close()
        self.assertEqual(CountedBackend.active, 0)

    def test_same_model_identity_is_reused_across_roles(self):
        pool = LocalModelPool({"actor": "same", "analyzer": "same"}, factory=CountedBackend)
        try:
            pool.role("actor").complete("initial")
            pool.role("analyzer").complete("inspect")
            self.assertEqual(len(pool.loads), 1)
            self.assertEqual([event["role"] for event in pool.ledger.events], ["actor", "analyzer"])
        finally:
            pool.close()

    def test_cli_dedicated_roles_are_both_called_and_share_recorded_budget(self):
        class JsonBackend(CountedBackend):
            def complete(self, prompt, role):
                reply = super().complete(prompt, role)
                value = {"actions": [{"op": "validate", "ok": True}], "done": True} if role == "actor" else {
                    "findings": [{"id": rid, "status": "unknown", "evidence": []}
                                 for rid in ("R_INPUT", "R_ORDER", "R_RESULT", "R_REPORT")]}
                reply["text"] = json.dumps(value)
                return reply
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            tasks = root / "tasks.json"
            tasks.write_text(json.dumps(build_tasks()[:1]), encoding="utf-8")
            with patch("intentlab.model_pool.LocalBackend", JsonBackend), redirect_stdout(io.StringIO()):
                main(["run", "--tasks", str(tasks), "--out", str(root / "run"),
                      "--actor-model-path", "fixed", "--analyzer-model-path", "trained", "--analyzer-interface", "schema",
                      "--policies", "none", "--max-repairs", "0", "--repeats", "1", "--token-budget", "20"])
            row = json.loads((root / "run/runs.jsonl").read_text(encoding="utf-8"))
            ledger = row["model_pool"]["shared_token_ledger"]
            self.assertEqual([event["role"] for event in ledger["events"]], ["actor", "analyzer"])
            self.assertEqual(ledger["charged_tokens"], 12)
            summary = json.loads((root / "run/summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["none"]["charged_model_tokens"], 12)
