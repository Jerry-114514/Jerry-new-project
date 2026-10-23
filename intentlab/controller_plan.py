"""Development-only strong fixed-k selection and first-stage ablation binding.

The heuristic-weight controls are not learning-rate risk-feedback controllers.
"""

import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath

from .core import canonical, digest
from .execution_audit import audit_records
from .execution_data import load_execution_tasks, load_references, validate_tasks
from .execution_protocol import contract_identity, validate_execution_settings
from .intensity import validate_intensity
from .report import save_json


def file_hash(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def absolute_record_path(path):
    # Archived provenance may come from Linux while replay runs on Windows.
    # Live file access still uses Path and must actually exist on this host.
    return isinstance(path, str) and (PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute())


def model_assets(paths):
    cache, result = {}, {}
    for role, path in paths.items():
        root = Path(path).resolve()
        if str(root) not in cache:
            files = {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(root.rglob("*")) if p.is_file()}
            if not files or not any(name.endswith(".safetensors") for name in files):
                raise ValueError("Development selection needs actual local model assets")
            cache[str(root)] = {"path": str(root), "files_sha256": files}
        result[role] = deepcopy(cache[str(root)])
    return result


def rank_fixed_arms(arms):
    """Equal weight per source task, then lower charged tokens, then smaller k."""
    scores = []
    for arm in arms:
        groups = defaultdict(list)
        for row in arm["records"]:
            groups[row["source_task_id"]].append((int(row["metrics"]["compliant_success"]),
                row["model_pool"]["shared_token_ledger"]["charged_tokens"]))
        if not groups:
            raise ValueError("No validation source tasks for fixed-k selection")
        success = sum(sum(x[0] for x in values) / len(values) for values in groups.values()) / len(groups)
        tokens = sum(sum(x[1] for x in values) / len(values) for values in groups.values()) / len(groups)
        scores.append({"k": arm["k"], "source_task_mean_compliant_success": success,
                       "source_task_mean_charged_tokens": tokens, "source_task_groups": len(groups)})
    best = min(scores, key=lambda row: (-row["source_task_mean_compliant_success"], row["source_task_mean_charged_tokens"], row["k"]))
    return {"selected_k": best["k"], "rule": "validation_task_mean_success_then_charged_tokens_then_smaller_k", "scores": scores}


def validate_selection(report, settings, cases=None, formal=False):
    config = validate_intensity(settings["intensity"])
    if report.get("kind") != "development_fixed_k_selection" or type(report.get("schema_version")) is not int or report.get("schema_version") != 1 \
            or report.get("status") != "completed" or report.get("heldout_used") is not False \
            or report.get("scope") not in {"engineering", "development"} or type(report.get("injected_pool")) is not bool \
            or report.get("report_hash") != digest({k: v for k, v in report.items() if k != "report_hash"}) \
            or (formal and (report.get("scope") != "development" or report.get("injected_pool"))):
        raise ValueError("Missing, changed or non-development fixed-k selection report")
    tasks = validate_tasks(report["tasks"])
    if not tasks or any(task["split"] != "validation" for task in tasks):
        raise ValueError("Strong fixed-k selection uses validation tasks only, never test/OOD")
    if report["model_assets_before"] != report["model_assets_after"]:
        raise ValueError("Development model assets changed during fixed-k selection")
    if set(report["model_assets_before"]) != {"actor", "analyzer"}:
        raise ValueError("Selection needs both model role identities")
    for record in report["model_assets_before"].values():
        assets = record["files_sha256"]
        if not absolute_record_path(record["path"]) or not assets or not any(name.endswith(".safetensors") for name in assets) \
                or any(not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value) for value in assets.values()):
            raise ValueError("Selection requires explicit local model asset SHA256 identities")
    if cases is not None:
        expected = {contract_identity(row, row["public"]) for row in cases if row["split"] == "validation"}
        actual = {contract_identity(task, dict(request=task["request"], inputs=task["inputs"],
            requirements=task["requirements"], execution_spec=task["spec"])) for task in tasks}
        if actual != expected:
            raise ValueError("Fixed-k development tasks differ from reviewed validation contracts")
    if any(type(arm["k"]) is not int for arm in report["arms"]) or [arm["k"] for arm in report["arms"]] != settings["fixed_k_values"]:
        raise ValueError("Selection must include every fixed k control")
    if set(report["budgets"]) != {"max_new_tokens", "token_budget", "context_limit", "max_repairs"} \
            or any(type(value) is not int or value < 1 for value in report["budgets"].values()):
        raise ValueError("Explicit positive integer development budgets required")
    references = {row["task_id"]: row for row in report["references"]}
    if len(references) != len(report["references"]) or set(references) != {task["id"] for task in tasks}:
        raise ValueError("Development static reference coverage differs")
    common = None
    for arm in report["arms"]:
        manifest = arm["manifest"]
        intensity = deepcopy(config)
        intensity["fixed_k"] = arm["k"]
        if manifest.get("scope") != "development" or manifest.get("policies") != ["fixed-k"] \
                or manifest.get("executor_is_language_model") is not True or manifest.get("hard_guard_enabled") is not True \
                or manifest.get("intensity_config") != intensity:
            raise ValueError("Fixed-k arms must share the frozen intensity and enabled hard guard")
        shared = {key: manifest[key] for key in ("model_paths", "analyzer_mode", "max_repairs", "max_tool_steps", "actor_envelope", "redact_events")}
        if common is not None and common != shared:
            raise ValueError("Development arms differ beyond fixed k")
        common = shared
        if manifest["analyzer_mode"] != settings["analyzer_mode"] or manifest["max_tool_steps"] != settings["max_tool_steps"] \
                or manifest["actor_envelope"] != settings["actor_envelope"] or manifest["redact_events"] != settings["redact_events"]:
            raise ValueError("Selection controls differ from the frozen execution settings")
        if manifest["max_repairs"] != report["budgets"]["max_repairs"]:
            raise ValueError("Selection repair cap differs from declared development budget")
        for row in arm["records"]:
            if row["split"] != "validation" or row["policy"] != "fixed-k" or row["hard_guard_enabled"] is not True:
                raise ValueError("Non-validation or unguarded fixed-k record")
            for role, path in row["model_pool"]["models"].items():
                if report["model_assets_before"][role]["path"] != path:
                    raise ValueError("Development role paths differ from recorded asset identity")
        audit_records(tasks, references, manifest, arm["records"])
    # Context/ledger limits must also match across arms, including error runs.
    budgets = {(row["model_pool"]["context_limit"], row["model_pool"]["shared_token_ledger"]["limit"])
               for arm in report["arms"] for row in arm["records"]}
    if len(budgets) != 1:
        raise ValueError("Development arms need identical context and shared token limits")
    if budgets != {(report["budgets"]["context_limit"], report["budgets"]["token_budget"])} or any(
            event["completion_allowance"] > report["budgets"]["max_new_tokens"]
            for arm in report["arms"] for row in arm["records"] for event in row["model_pool"]["shared_token_ledger"]["events"]
            if event["status"] != "denied"):
        raise ValueError("Actual selection context/token caps differ from declared budget")
    selection = rank_fixed_arms(report["arms"])
    if report["selection"] != selection:
        raise ValueError("Strong fixed k was not selected by the declared validation rule")
    return selection


def run_selection(tasks, references, paths, settings, budgets, out, device="cpu", engineering=False, pool_factory=None):
    from .execution import run_execution
    from .model_pool import LocalModelPool
    validate_execution_settings(settings)
    validate_tasks(tasks)
    if any(task["split"] != "validation" for task in tasks):
        raise ValueError("Development selection rejects train/test/OOD tasks")
    if pool_factory is not None and not engineering:
        raise ValueError("Injected development selection must explicitly be engineering")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    report = {"kind": "development_fixed_k_selection", "schema_version": 1,
        "scope": "engineering" if engineering else "development", "status": "running", "heldout_used": False,
        "injected_pool": pool_factory is not None, "tasks": deepcopy(tasks), "references": list(references.values()), "arms": [],
        "budgets": deepcopy(budgets),
        "warning": "Validation pilot selection only; includes all failures and is not formal training or human verification."}
    save_json(out / "selection.json", report)
    try:
        report["model_assets_before"] = model_assets(paths)
        for k in settings["fixed_k_values"]:
            pool = (pool_factory or LocalModelPool)(paths, device=device, max_new_tokens=budgets["max_new_tokens"],
                token_budget=budgets["token_budget"], context_limit=budgets["context_limit"])
            intensity = deepcopy(settings["intensity"])
            intensity["fixed_k"] = k
            result = run_execution(tasks, references, out / f"fixed-k-{k}", pool=pool, policies=("fixed-k",),
                max_repairs=budgets["max_repairs"], hard_guard=True, redact_events=settings["redact_events"],
                max_tool_steps=settings["max_tool_steps"], actor_envelope=settings["actor_envelope"],
                intensity_config=intensity, analyzer_mode=settings["analyzer_mode"])
            from .formal_data import read_jsonl
            report["arms"].append({"k": k, "manifest": result["manifest"], "records": read_jsonl(out / f"fixed-k-{k}/runs.jsonl")})
            save_json(out / "selection.json", report)
        report["model_assets_after"] = model_assets(paths)
        report.update(status="completed", selection=rank_fixed_arms(report["arms"]))
        report["report_hash"] = digest(report)
        validate_selection(report, settings)
    except Exception as exc:
        report.pop("report_hash", None)
        report.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        save_json(out / "selection.json", report)
        raise
    save_json(out / "selection.json", report)
    return report


def bind_plan(path, settings, cases, formal=False, budgets=None, programmatic=False):
    path = Path(path).resolve()
    plan_sha = file_hash(path)
    plan = json.loads(path.read_text(encoding="utf-8"))
    last_key = 'label_scope' if programmatic else 'reviewers'
    if set(plan) != {"schema_version", "stage", "selection_report", "risk_controls", "lr_risk_feedback", last_key} \
            or type(plan["schema_version"]) is not int or plan["schema_version"] != (2 if programmatic else 1) or plan["stage"] != "first_stage_execution_intensity" \
            or plan["risk_controls"] != ["remove_hard_weight", "remove_unknown_weight"] \
            or plan["lr_risk_feedback"] != "deferred_exploratory_requires_new_unseen_test":
        raise ValueError("Explicit first-stage intensity controls and deferred LR risk feedback required")
    if programmatic:
        from .programmatic_protocol import SCOPE
        if plan['label_scope'] != SCOPE:
            raise ValueError('Programmatic controller claims scope mismatch')
    reviewers = plan.get("reviewers")
    if not programmatic and (not isinstance(reviewers, list) or len(reviewers) != 2 or any(
            set(row) != {"reviewer", "human_verified", "notes"} or row["human_verified"] is not True
            or not isinstance(row["reviewer"], str) or not row["reviewer"].strip()
            or not isinstance(row["notes"], str) or not row["notes"].strip() for row in reviewers) \
            or reviewers[0]["reviewer"] == reviewers[1]["reviewer"]):
        raise ValueError("Two distinct controller review declarations required; identity authenticity is external")
    record = plan["selection_report"]
    if set(record) != {"path", "sha256"} or not Path(record["path"]).is_absolute() or file_hash(record["path"]) != record["sha256"]:
        raise ValueError("Bind the exact development selection report with an absolute path and SHA256")
    report = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    selection = validate_selection(report, settings, cases, formal)
    if budgets is not None and report["budgets"] != budgets:
        raise ValueError("Development selection and frozen execution must share the same budgets")
    if file_hash(path) != plan_sha or file_hash(record["path"]) != record["sha256"]:
        raise ValueError("Controller evidence changed while binding")
    return {"plan": deepcopy(plan), "selection": selection,
        "files": {"plan": {"path": str(path), "sha256": plan_sha}, "selection_report": deepcopy(record)},
        "warning": "Checks supplied review declarations and development trace consistency, not human authenticity or statistical adequacy."}


def condition_map(binding, settings):
    config = validate_intensity(settings["intensity"])
    result = {}
    for k in settings["fixed_k_values"]:
        intensity = deepcopy(config)
        intensity["fixed_k"] = k
        result[f"fixed-k-{k}"] = {"policy": "fixed-k", "hard_guard": True, "intensity": intensity}
    result["dynamic-k"] = {"policy": "dynamic-k", "hard_guard": True, "intensity": deepcopy(config)}
    for name in binding["plan"]["risk_controls"]:
        intensity = deepcopy(config)
        intensity["hard_weight" if name == "remove_hard_weight" else "unknown_weight"] = 1.0 if name == "remove_hard_weight" else 0.0
        result["dynamic-k-" + name] = {"policy": "dynamic-k", "hard_guard": True, "intensity": intensity}
    if binding["selection"]["selected_k"] not in settings["fixed_k_values"]:
        raise ValueError("Development-selected strong fixed k missing from controls")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True, help="Protocol draft; selection uses only execution settings and budgets")
    parser.add_argument("--actor-model", type=Path, required=True)
    parser.add_argument("--analyzer-model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--engineering", action="store_true")
    args = parser.parse_args()
    spec = json.loads(args.settings.read_text(encoding="utf-8"))
    tasks = load_execution_tasks(args.tasks)
    report = run_selection(tasks, load_references(args.references, tasks), {"actor": str(args.actor_model.resolve()),
        "analyzer": str(args.analyzer_model.resolve())}, spec["execution"]["settings"], spec["budgets"], args.out, args.device, args.engineering)
    print(json.dumps(report["selection"], indent=2))


if __name__ == "__main__":
    main()
