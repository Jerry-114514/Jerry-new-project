"""Auditable repair-root count selection using public findings only.

The score is a fixed heuristic severity index, not a calibrated probability.
Dependency closure is shared by both arms and may expand beyond k roots.
"""

from copy import deepcopy
import math


DEFAULT_INTENSITY = {
    "schema_version": 1, "fixed_k": 1, "max_k": 3,
    "thresholds": [0.25, 0.5], "hard_weight": 2.0, "unknown_weight": 0.5,
}


def validate_intensity(config):
    if not isinstance(config, dict) or set(config) != set(DEFAULT_INTENSITY) or type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise ValueError("Repair intensity fields must match schema_version=1")
    if type(config["max_k"]) is not int or not 1 <= config["max_k"] <= 8 \
            or type(config["fixed_k"]) is not int or not 1 <= config["fixed_k"] <= config["max_k"]:
        raise ValueError("Require 1 <= fixed_k <= max_k <= 8")
    thresholds = config["thresholds"]
    def finite(value):
        return type(value) in {int, float} and math.isfinite(value)
    if not isinstance(thresholds, list) or len(thresholds) != config["max_k"] - 1 \
            or any(not finite(x) or not 0 < x < 1 for x in thresholds) \
            or any(a >= b for a, b in zip(thresholds, thresholds[1:])):
        raise ValueError("Require max_k-1 strictly increasing thresholds inside (0,1)")
    if not finite(config["hard_weight"]) or not 1 <= config["hard_weight"] <= 100 \
            or not finite(config["unknown_weight"]) or not 0 <= config["unknown_weight"] <= 1:
        raise ValueError("Invalid public severity weights")
    return deepcopy(config)


def choose_intensity(task, findings, policy, config):
    config = validate_intensity(config)
    if policy not in {"fixed-k", "dynamic-k"}:
        raise ValueError("Intensity requires fixed-k or dynamic-k")
    requirements = {row["id"]: row for row in task["requirements"]}
    if not requirements or len(findings) != len(requirements) or {row["id"] for row in findings} != set(requirements):
        raise ValueError("Intensity requires exactly one finding per public requirement")
    numerator = denominator = 0.0
    for row in findings:
        req = requirements[row["id"]]
        if type(row["hard"]) is not bool or row["hard"] != req["hard"] or row["status"] not in {"satisfied", "violated", "unknown"}:
            raise ValueError("Invalid intensity finding or changed public hard flag")
        weight = config["hard_weight"] if req["hard"] else 1.0
        denominator += weight
        numerator += weight * (1.0 if row["status"] == "violated" else config["unknown_weight"] if row["status"] == "unknown" else 0.0)
    severity = numerator / denominator
    requested_k = config["fixed_k"] if policy == "fixed-k" else 1 + sum(severity >= cut for cut in config["thresholds"])
    # Identical ordering in both arms; do not read learned scores or offline truth.
    failures = sorted((row for row in findings if row["status"] == "violated"), key=lambda row: (not row["hard"], row["id"]))
    roots = [row["id"] for row in failures[:requested_k]]
    dependencies = task["spec"]["dependencies"]
    if set(dependencies) != set(requirements) or any(not isinstance(ids, list) or any(rid not in requirements for rid in ids) for ids in dependencies.values()):
        raise ValueError("Intensity requires a complete public dependency graph")
    selected, pending = set(roots), list(roots)
    while pending:
        for rid in dependencies[pending.pop()]:
            if rid not in selected:
                selected.add(rid)
                pending.append(rid)
    return {"policy": policy, "severity_index": severity, "weighted_failure_mass": numerator,
            "total_requirement_weight": denominator, "requested_k": requested_k,
            "selected_root_count": len(roots), "roots": roots, "target": sorted(selected),
            "expanded_target_count": len(selected), "config": config}
