"""Synthetic M6/M7 registration and residency audit, never efficacy evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from intentlab import frozen_ablation
from intentlab.core import digest
from intentlab.diagnostic_protocol import generate, reveal as reveal_diagnostics
from intentlab.execution_protocol import validate_execution_settings
from intentlab.formal_data import read_jsonl
from intentlab.frozen_execution import interact, reveal, verify_interactions, audit_shared_residency
from intentlab.gpu_lease import GpuBusy
from intentlab.protocol import freeze
from test_controller_plan import prepare_controller_plan
from test_diagnostic_protocol import FakeBackend, fake_loss
from test_execution_protocol import fixture
from test_frozen_execution import FakePool, FakeRole


class ResidentPool(FakePool):
    instances = []
    interfere = False

    def __init__(self, paths, device, max_new_tokens, token_budget, context_limit, share_base_adapter=False):
        assert share_base_adapter
        super().__init__(paths, device, max_new_tokens, token_budget, context_limit)
        self.resident = False
        self.resident_at_task_start = False
        self.loads = []
        self.total_loads = self.total_releases = 0
        self.instances.append(self)

    def reset(self):
        super().reset()
        self.resident_at_task_start = self.resident
        self.loads = []

    def role(self, role):
        pool = self
        class Role:
            def complete(self, prompt):
                if not pool.resident:
                    pool.loads.append({"role": role, "path": pool.paths[role], "status": "loaded", "seconds": 0.0})
                    pool.total_loads += 1
                    pool.resident = True
                if pool.interfere:
                    raise GpuBusy("Other CUDA compute processes are active (PIDs 123)")
                return FakeRole(pool, role).complete(prompt)
        return Role()

    def close(self):
        if self.resident:
            self.total_releases += 1
        self.resident = False

    def snapshot(self):
        return {**super().snapshot(), "residency_strategy": "shared-base-adapter",
                "resident_at_task_start": self.resident_at_task_start, "model_loads": deepcopy(self.loads)}


def prepare(root, policy):
    spec = fixture(root / "fixture")
    spec["execution"]["settings"]["model_residency"] = policy
    prepare_controller_plan(spec, root, FakePool)
    lock = freeze(spec, root / "protocol.json")
    binding = {"binding_hash": "synthetic-residency-no-weights", "matrix": {"root": str(root / "matrix")},
               "models": {"actor": lock["models"]["actor"], "analyzer": lock["models"]["analyzer_base"]}}
    generate(lock, binding, root / "predictions", True, FakeBackend)
    reveal_diagnostics(lock, binding, root / "predictions", root / "diagnostics", True, fake_loss)
    return spec, lock, binding


@patch("intentlab.diagnostic_protocol.verify_execution_models", return_value={"verified": True})
class ResidencyExecutionTests(unittest.TestCase):
    def test_registered_m6_and_m7_keep_weights_within_conditions_and_match_cold_results(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, lock, binding = prepare(root / "shared", "shared-condition-v1")
            path = root / "shared"
            args = (lock, binding, path / "predictions", path / "diagnostics")
            manifest = interact(*args, path / "m6", True, ResidentPool)
            pool = ResidentPool.instances[-1]
            self.assertEqual((pool.total_loads, pool.total_releases), (4, 4))
            self.assertFalse(pool.resident)
            self.assertEqual(manifest["schema_version"], 2)
            _, _, rows = verify_interactions(*args, path / "m6", True)
            self.assertEqual([r["model_pool"]["resident_at_task_start"] for r in rows], [False, True] * 4)
            self.assertEqual([r["model_pool"]["shared_token_ledger"]["events"][0]["role"] for r in rows], ["actor"] * 8)
            reveal(*args, path / "m6", path / "m6-reveal", True)
            ablation_args = (*args, path / "m6", path / "m6-reveal")
            frozen_ablation.interact(*ablation_args, path / "m7", True, ResidentPool)
            pool = ResidentPool.instances[-1]
            self.assertEqual((pool.total_loads, pool.total_releases), (6, 6))
            frozen_ablation.verify_interactions(*ablation_args, path / "m7", True)
            frozen_ablation.reveal(*ablation_args, path / "m7", path / "m7-reveal", True)
            self.assertFalse(frozen_ablation.verify_scoring(*ablation_args, path / "m7", path / "m7-reveal", True)["references_reopened"])
            _, cold_lock, cold_binding = prepare(root / "cold", "cold-task-v1")
            cold = root / "cold"
            old = interact(cold_lock, cold_binding, cold / "predictions", cold / "diagnostics", cold / "m6", True, FakePool)
            self.assertEqual(old["schema_version"], 1)
            cold_rows = read_jsonl(cold / "m6/interactions.jsonl")
            self.assertEqual([{k: r[k] for k in ("condition", "status", "history", "final_state", "cost")} for r in rows],
                             [{k: r[k] for k in ("condition", "status", "history", "final_state", "cost")} for r in cold_rows])

    def test_rehashed_wrong_residency_and_missing_release_timing_are_rejected(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, lock, binding = prepare(root, "shared-condition-v1")
            args = (lock, binding, root / "predictions", root / "diagnostics")
            manifest = interact(*args, root / "m6", True, ResidentPool)
            rows = read_jsonl(root / "m6/interactions.jsonl")
            conditions = manifest["conditions"]
            for case in ("warm_condition_start", "extra_reload", "missing_timing", "omitted_total", "wrong_strategy", "omitted_loading"):
                altered, records = deepcopy(manifest), deepcopy(rows)
                if case == "warm_condition_start":
                    records[0]["model_pool"]["resident_at_task_start"] = True
                elif case == "extra_reload":
                    records[1]["model_pool"]["model_loads"] = deepcopy(records[0]["model_pool"]["model_loads"])
                elif case == "missing_timing":
                    altered["condition_timings"].pop(next(iter(conditions)))
                elif case == "omitted_total":
                    altered["seconds_including_loading"] = 0
                elif case == "omitted_loading":
                    records[0]["model_pool"]["model_loads"][0]["seconds"] = altered["seconds_including_loading"] + 1
                else:
                    records[0]["model_pool"]["residency_strategy"] = "reload-by-path"
                altered["seal_hash"] = digest({k: v for k, v in altered.items() if k != "seal_hash"})
                with self.assertRaises(ValueError, msg=case):
                    audit_shared_residency(altered, records, conditions)

    def test_resource_incident_still_persists_trial_and_releases_shared_weights(self, unused):
        class BusyResidentPool(ResidentPool):
            interfere = True
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, lock, binding = prepare(root, "shared-condition-v1")
            with self.assertRaises(GpuBusy):
                interact(lock, binding, root / "predictions", root / "diagnostics", root / "m6", True, BusyResidentPool)
            pool = ResidentPool.instances[-1]
            self.assertEqual((pool.total_loads, pool.total_releases), (1, 1))
            self.assertEqual(json.loads((root / "m6/manifest.json").read_text())["status"], "failed")
            self.assertEqual(len(read_jsonl(root / "m6/interactions.jsonl")), 1)

    def test_unknown_residency_is_not_silently_accepted(self, unused):
        with tempfile.TemporaryDirectory() as name:
            spec = fixture(name)
            settings = spec["execution"]["settings"]
            for value in ("automatic", [], True):
                with self.assertRaises(ValueError):
                    validate_execution_settings(dict(settings, model_residency=value))
