"""Coordinator-only execution binding; never called by an online analyzer.

This validates reviewed public task identity and independently reviewed static
references. It does not use the public solver to certify its own answers.
"""

from collections import Counter, defaultdict

from .core import canonical, digest
from .execution_data import load_execution_tasks, load_references
from .formal_data import validate_cases
from .intensity import validate_intensity


SETTING_KEYS = {"analyzer_condition", "analyzer_seed", "checkpoint_selection", "analyzer_mode",
                "dynamic_policy", "intensity", "fixed_k_values", "max_tool_steps", "actor_envelope", "redact_events"}


def validate_execution_settings(settings):
    if not isinstance(settings, dict) or set(settings) not in (SETTING_KEYS, SETTING_KEYS | {"model_residency"}):
        raise ValueError("Execution settings must explicitly bind all runtime/controller choices")
    residency = settings.get("model_residency", "cold-task-v1")
    if not isinstance(residency, str) or residency not in {"cold-task-v1", "shared-condition-v1"}:
        raise ValueError("Unknown registered model residency policy")
    if settings["analyzer_condition"] not in {"D", "E"} or type(settings["analyzer_seed"]) is not int or settings["analyzer_seed"] not in {0, 1, 2}:
        raise ValueError("Predeclare a trained D/E analyzer and one of the paired seeds")
    if settings["checkpoint_selection"] != "best_validation_loss":
        raise ValueError("Execution analyzer must be selected by validation loss, never test")
    if settings["analyzer_mode"] not in {"model", "hybrid"} or settings["dynamic_policy"] != "dynamic-k":
        raise ValueError("Bind an explicit model/hybrid analyzer and dynamic-k policy")
    config = validate_intensity(settings["intensity"])
    fixed = settings["fixed_k_values"]
    if not isinstance(fixed, list) or any(type(k) is not int for k in fixed) or fixed != list(range(1, config["max_k"] + 1)):
        raise ValueError("Predeclare all fixed k controls from one through max_k")
    if type(settings["max_tool_steps"]) is not int or not 1 <= settings["max_tool_steps"] <= 8:
        raise ValueError("Bind one to eight tool feedback steps")
    if settings["actor_envelope"] not in {"strict", "extract"} or type(settings["redact_events"]) is not bool:
        raise ValueError("Explicit actor normalization and history visibility required")
    return settings


def execution_condition_map(settings):
    validate_execution_settings(settings)
    return {name: {"policy": "fixed-full" if name in {"P1", "P3"} else settings["dynamic_policy"],
                   "hard_guard": name in {"P3", "P4"}} for name in ("P1", "P2", "P3", "P4")}


def contract_identity(row, public):
    return digest({"group": {key: row[key] for key in ("source_task_id", "family", "split", "template_id")},
                   "source": {key: row["source"][key] for key in ("origin", "license")},
                   "public": {key: public.get(key) for key in ("request", "inputs", "requirements", "execution_spec")}})


def validate_execution_binding(execution, diagnostic_cases, audit_path, programmatic=False):
    if not isinstance(execution, dict) or set(execution) != {"tasks", "references", "settings"}:
        raise ValueError("Execution binding requires tasks/references/settings")
    settings = validate_execution_settings(execution["settings"])
    tasks = load_execution_tasks(execution["tasks"])
    references = load_references(execution["references"], tasks)
    validate_cases(diagnostic_cases)
    heldout = [case for case in diagnostic_cases if case["split"] in {"test", "ood"}]
    groups = {case["source_task_id"] for case in heldout}
    expected = {contract_identity(case, case["public"]) for case in heldout}
    actual = Counter()
    for task in tasks:
        if task["split"] not in {"test", "ood"}:
            raise ValueError("Confirmatory execution binding contains a non-held-out task")
        public = {key: task[key] for key in ("request", "inputs", "requirements")}
        public["execution_spec"] = task["spec"]
        actual[contract_identity(task, public)] += 1
    if not groups or actual != Counter({identity: 1 for identity in expected}):
        raise ValueError("Execution contracts differ from reviewed test/OOD variants or have missing/duplicate variants")
    # Structured signatures in the existing execution/oracle evidence file.
    # Reviewers inspect static outputs independently; these are declarations,
    # not automatically generated diagnostic labels or proof of real identity.
    import json
    from pathlib import Path
    audit = json.loads(Path(audit_path).read_text(encoding="utf-8"))
    if programmatic:
        from .spec_reference import verify_references
        if canonical(audit) != canonical(verify_references(tasks, references)):
            raise ValueError('Programmatic execution reference evidence differs from independent recomputation')
        return {"tasks": len(tasks), "source_task_groups": len(groups), "contract_variants": len(expected),
            "splits": dict(Counter(task["split"] for task in tasks)),
            "tasks_hash": digest(tasks), "references_hash": digest(references),
            "condition_map": execution_condition_map(settings),
            "warning": "Encoded-spec reference recomputation; no human evaluation or formal proof."}
    if not isinstance(audit, dict) or set(audit) != {"schema_version", "tasks_hash", "references_hash", "reviews"} \
            or type(audit["schema_version"]) is not int or audit["schema_version"] != 1 \
            or audit["tasks_hash"] != digest(tasks) or audit["references_hash"] != digest(references):
        raise ValueError("Execution/oracle audit must bind the exact tasks and independent references")
    reviewed = defaultdict(set)
    ids = {task["id"] for task in tasks}
    if not isinstance(audit["reviews"], list):
        raise ValueError("Execution audit requires per-task independent review records")
    for review in audit["reviews"]:
        if not isinstance(review, dict) or set(review) != {"task_id", "reviewer", "human_verified", "contract_verified", "reference_verified", "notes"}:
            raise ValueError("Unsupported execution review fields")
        rid, tid = review["reviewer"], review["task_id"]
        if not isinstance(rid, str) or not rid.strip() or tid not in ids or rid in reviewed[tid] \
                or any(review[key] is not True for key in ("human_verified", "contract_verified", "reference_verified")) \
                or not isinstance(review["notes"], str) or not review["notes"].strip():
            raise ValueError("Missing real contract/reference verification or duplicate reviewer")
        reviewed[tid].add(rid)
    if set(reviewed) != ids or any(len(names) != 2 for names in reviewed.values()):
        raise ValueError("Two independent contract/reference reviewers required for every execution task")
    return {"tasks": len(tasks), "source_task_groups": len(groups), "contract_variants": len(expected),
            "splits": dict(Counter(task["split"] for task in tasks)),
            "tasks_hash": digest(tasks), "references_hash": digest(references),
            "condition_map": execution_condition_map(settings),
            "warning": "Validates supplied signatures/identity linkage, not human authenticity or scientific adequacy."}
