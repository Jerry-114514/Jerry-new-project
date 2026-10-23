"""Bind actual validation-selected exports after all six paired jobs complete.

This stage reads train/validation provenance and model tensors only. It does
not open held-out diagnostic gold, execution tasks/references or human reviews.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from .checkpoint_selection import verify_selected_checkpoint
from .core import canonical, digest
from .matrix import configurations, paired_training_audit
from .protocol import file_hash, read_json, verify


def export_snapshot(directory):
    root = Path(directory).resolve()
    files = {path.relative_to(root).as_posix(): file_hash(path) for path in sorted(root.rglob("*")) if path.is_file()}
    if not files or "selection.json" not in files or not any(name.endswith(".safetensors") for name in files):
        raise ValueError("Missing selected model export assets")
    return {"path": str(root), "files_sha256": files}


def completed_matrix(protocol, matrix_root, engineering=False):
    verify(protocol, "training")
    if protocol["spec"].get("schema_version") not in {2, 3}:
        raise ValueError("Execution models require a v2/v3 training protocol")
    if protocol["scope"] == "engineering" and not engineering:
        raise ValueError("Synthetic engineering protocols need explicit --engineering")
    root = Path(matrix_root).resolve()
    matrix = read_json(root / "matrix.json")
    if matrix.get("kind") != "paired_training_matrix" or matrix.get("scope") != protocol["scope"] \
            or matrix.get("status") != "completed" or matrix.get("lock_hash") != protocol["lock_hash"] \
            or matrix.get("heldout_evaluated") is not False:
        raise ValueError("All six paired jobs must finish under this protocol without held-out evaluation")
    if [(job["name"], job["config"]) for job in matrix["jobs"]] != configurations(protocol):
        raise ValueError("Completed matrix differs from the exact frozen six-job plan")
    pairs = paired_training_audit(matrix["jobs"], root)
    if canonical(pairs) != canonical(matrix.get("paired_audit")):
        raise ValueError("Paired training audit changed")
    return matrix


def bind_execution_models(protocol, matrix_root, out, engineering=False):
    root, out = Path(matrix_root).resolve(), Path(out)
    if out.exists():
        raise ValueError("Do not overwrite a model binding")
    matrix_sha = file_hash(root / "matrix.json")
    matrix = completed_matrix(protocol, root, engineering)
    selections = {}
    for job in matrix["jobs"]:
        result = read_json(root / job["name"] / "result.json")
        selections[job["name"]] = verify_selected_checkpoint(root / job["name"], result)
    settings = protocol["spec"]["execution"]["settings"]
    schedule = {"D": "cosine", "E": "plateau"}[settings["analyzer_condition"]]
    name = f"{schedule}-seed-{settings['analyzer_seed']}"
    job = next(job for job in matrix["jobs"] if job["name"] == name)
    analyzer = export_snapshot(root / name / "model")
    expected = {key.removeprefix("model/"): value for key, value in job["artifacts_sha256"].items() if key.startswith("model/")}
    if analyzer["files_sha256"] != expected:
        raise ValueError("Analyzer assets differ from the completed training export")
    if protocol["scope"] == "formal":
        adapter = read_json(Path(analyzer["path"]) / "adapter_config.json")
        if (Path(analyzer["path"]) / "tiny_base_recipe.json").exists() or adapter.get("peft_type") != "LORA" \
                or Path(adapter["base_model_name_or_path"]).resolve() != Path(protocol["models"]["analyzer_base"]["path"]):
            raise ValueError("Formal analyzer must use its frozen original base, not another adapter recipe")
    if file_hash(root / "matrix.json") != matrix_sha:
        raise ValueError("Matrix changed while binding models")
    binding = {"kind": "execution_model_lock", "schema_version": 1, "scope": protocol["scope"],
        "created_utc": datetime.now(timezone.utc).isoformat(), "training_protocol_hash": protocol["lock_hash"],
        "matrix": {"root": str(root), "sha256": matrix_sha}, "selected_job": name,
        "selected_result_sha256": job["result_sha256"], "selected_checkpoint_sha256": job["artifacts_sha256"]["latest.pt"],
        "settings_hash": digest(settings), "selections": selections,
        "models": {"actor": deepcopy(protocol["models"]["actor"]), "analyzer": analyzer},
        "hidden_inputs_opened": False,
        "warning": "Weight/provenance binding, not test evaluation or a scientific efficacy result."}
    binding["binding_hash"] = digest(binding)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(binding, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return binding


def verify_execution_models(protocol, binding, engineering=False):
    if binding.get("kind") != "execution_model_lock" or binding.get("schema_version") != 1 \
            or digest({key: value for key, value in binding.items() if key != "binding_hash"}) != binding.get("binding_hash"):
        raise ValueError("Execution model binding content changed")
    if binding["scope"] != protocol["scope"] or binding["training_protocol_hash"] != protocol["lock_hash"] \
            or binding["settings_hash"] != digest(protocol["spec"]["execution"]["settings"]):
        raise ValueError("Model binding belongs to another frozen protocol/settings")
    root = Path(binding["matrix"]["root"])
    if file_hash(root / "matrix.json") != binding["matrix"]["sha256"]:
        raise ValueError("Training matrix changed after model binding")
    matrix = completed_matrix(protocol, root, engineering)
    settings = protocol["spec"]["execution"]["settings"]
    name = {"D": "cosine", "E": "plateau"}[settings["analyzer_condition"]] + "-seed-" + str(settings["analyzer_seed"])
    job = next(job for job in matrix["jobs"] if job["name"] == name)
    if binding["selected_job"] != name or binding["selected_result_sha256"] != job["result_sha256"] \
            or binding["selected_checkpoint_sha256"] != job["artifacts_sha256"]["latest.pt"] \
            or binding["models"]["actor"] != protocol["models"]["actor"] \
            or Path(binding["models"]["analyzer"]["path"]) != (root / name / "model").resolve():
        raise ValueError("Selected role/checkpoint identity changed")
    if export_snapshot(root / name / "model") != binding["models"]["analyzer"]:
        raise ValueError("Bound analyzer assets changed")
    actual = verify_selected_checkpoint(root / name, read_json(root / name / "result.json"))
    if canonical(actual) != canonical(binding["selections"][name]):
        raise ValueError("Selected checkpoint proof changed")
    return {"verified": True, "binding_hash": binding["binding_hash"], "selected_job": name, "hidden_inputs_opened": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["bind", "verify"])
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--matrix", type=Path)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--engineering", action="store_true")
    args = parser.parse_args()
    protocol = read_json(args.protocol)
    if args.command == "bind":
        if args.matrix is None or args.out is None:
            parser.error("bind needs --matrix and --out")
        result = bind_execution_models(protocol, args.matrix, args.out, args.engineering)
        result = {"binding_hash": result["binding_hash"], "selected_job": result["selected_job"], "scope": result["scope"]}
    else:
        if args.binding is None:
            parser.error("verify needs --binding")
        result = verify_execution_models(protocol, read_json(args.binding), args.engineering)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
