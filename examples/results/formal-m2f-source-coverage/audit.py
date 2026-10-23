"""Publish metadata-only combined source triage; never approve sources or labels."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO))
from intentlab.core import digest
from intentlab.formal_data import read_jsonl, write_jsonl
from intentlab.source_triage import write_triage, validate_semantic_review

PIN = "65f35a9a38265bdc8c6fdfeb7e4707505e4e956b"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def public_inventory():
    output = subprocess.check_output(["git", "-C", str(REPO), "ls-tree", "-r", "--long", PIN], text=True)
    entries = []
    for line in output.splitlines():
        info, path = line.split("\t", 1)
        if path.startswith(("data/", "examples/results/")) and path.endswith((".json", ".jsonl")):
            mode, kind, blob, size = info.split()
            assert kind == "blob"
            entries.append({"path": path, "git_blob_sha1": blob, "git_bytes": int(size)})
    return {"commit": PIN, "scope": "tracked data/ and examples/results/ JSON/JSONL path inventory",
        "assets": entries, "asset_count": len(entries), "content_or_semantic_review_complete": False,
        "warning": "Git path/blob inventory only. Includes metadata and duplicate copies; not 1034 datasets or independence review. Excludes Markdown, logs, untracked files, other repositories and pretraining corpora."}


def batches(injected, natural):
    return {"legacy-development": read_jsonl(REPO / "examples/results/formal-m2b-source-triage/triage/coordinator-cases.jsonl"),
        "wikisql-injected": read_jsonl(injected),
        "wikisql-natural": read_jsonl(natural / "first-two/intake/coordinator-cases.jsonl") +
                           read_jsonl(natural / "remaining-ten/intake/coordinator-cases.jsonl")}


def metadata(private):
    contracts = read_jsonl(private / "contracts.jsonl")
    return [{**{key: row[key] for key in ("contract_id", "source_task_id", "template_id", "family", "split", "batches")},
             "view_count": len(row["case_ids"])} for row in contracts]


def prepare(injected, natural, out):
    if not out.resolve().is_relative_to((REPO / "runs/formal-private").resolve()):
        raise ValueError("Private source review must stay under ignored runs/formal-private")
    archive = out.parent / (out.name + "-coordinator.zip")
    if archive.exists():
        raise ValueError("Do not replace an existing coordinator package")
    summary = write_triage(batches(injected, natural), out, private=True)
    write_jsonl(ROOT / "contracts-index.jsonl", metadata(out))
    for name in ("summary.json", "candidate-pairs.jsonl", "semantic-review-template.json"):
        (ROOT / name).write_bytes((out / name).read_bytes())
    (ROOT / "prior-public-inventory.json").write_text(json.dumps(public_inventory(), indent=2) + "\n", encoding="utf-8", newline="\n")
    (out / "prior-public-inventory.json").write_bytes((ROOT / "prior-public-inventory.json").read_bytes())
    (out / "协调人说明.md").write_text("""# 来源审查协调人包

104 个开发视图、32 份合同、24 个声明来源，均未人工审核。
来源/模板/语义审查与逐要求状态双人标注是不同任务，不得相互替代。
78 对只是自动风险线索，包括 12 对跨 train/validation 的同操作合同。
12 份 WikiSQL 衍生合同共享一个模板；自然与注入轨迹共享源合同。
既往公开资产清单只是 Git 路径与版本目录，并未审阅全部内容。

审查所有 source_groups 的原始出处、生成谱系、合组、划分及未标记关系。
逐一填写 independence_rationale、provenance_evidence 和 pair_reviews 的决定与理由。
发现同源、重复或无法证明独立，先合组/排除/重划分，再对新数据重新生成审查。
不得直接将同模板风险全部勾选独立，也不得根据指标选择保留题目。
阅毕实际记录 prior_public_inventory_reference 和审查局限，最后才填写真人身份及确认。
空表和自动报告不能作为正式审核凭据。合同与来源内容保持私有，不发给盲标初审人。
""", encoding="utf-8", newline="\n")
    with ZipFile(archive, "w", ZIP_DEFLATED) as zipped:
        for path in sorted(out.iterdir()):
            zipped.write(path, path.name)
    manifest = {"kind": "private_unreviewed_source_coordinator_package", "human_reviews_completed": 0,
        "distributed": False, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "files_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()},
        "source_groups_to_review": 24, "flagged_pairs_to_review": 78, "formal_readiness_evidence": False}
    (ROOT / "coordinator-package.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return summary


def audit(injected=None, natural=None):
    assert (injected is None) == (natural is None)
    summary, contracts = read(ROOT / "summary.json"), read_jsonl(ROOT / "contracts-index.jsonl")
    pairs = read_jsonl(ROOT / "candidate-pairs.jsonl")
    assert [summary[k] for k in ("input_memberships", "unique_case_ids", "unique_public_contracts", "declared_source_ids")] == [104, 104, 32, 24]
    assert summary["scope"] == "private_coordinator" and summary["human_reviews_completed"] == 0
    assert summary["semantic_dedup_review_complete"] is summary["formal_readiness_evidence"] is False
    assert len(contracts) == len({r["contract_id"] for r in contracts}) == 32
    assert sum(r["view_count"] for r in contracts) == 104
    assert len({r["source_task_id"] for r in contracts}) == 24
    assert len(pairs) == summary["flagged_contract_pairs"] == 78
    assert sum(p["cross_split"] for p in pairs) == summary["flagged_cross_split_pairs"] == 12
    assert dict(Counter(reason for pair in pairs for reason in pair["reasons"])) == summary["reason_counts"]
    assert digest(pairs) == summary["queue_hash"]
    template = read(ROOT / "semantic-review-template.json")
    assert template["human_verified"] is False and template["reviewer"] == ""
    assert len(template["source_groups"]) == 24 and len(template["pair_reviews"]) == 78
    assert all(r["decision"] == r["rationale"] == "" for r in template["pair_reviews"])
    assert read(ROOT / "prior-public-inventory.json") == public_inventory()
    package = read(ROOT / "coordinator-package.json")
    assert package["human_reviews_completed"] == 0 and package["distributed"] is False
    assert package["source_groups_to_review"] == 24 and package["flagged_pairs_to_review"] == 78
    assert package["formal_readiness_evidence"] is False
    assert "prior-public-inventory.json" in package["files_sha256"]
    if injected is not None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "triage"
            reproduced = write_triage(batches(injected, natural), out, private=True)
            assert reproduced == summary and metadata(out) == contracts
            assert (out / "candidate-pairs.jsonl").read_bytes() == (ROOT / "candidate-pairs.jsonl").read_bytes()
            assert read(out / "semantic-review-template.json") == template
            try:
                validate_semantic_review(read_jsonl(out / "coordinator-cases.jsonl"), template)
            except ValueError as error:
                assert "Actual human" in str(error)
            else:
                raise AssertionError("Blank human source review was accepted")
    return {"scope": "unreviewed_combined_source_risk_inventory", "views":104,"contracts":32,
        "declared_sources":24,"flagged_pairs":78,"cross_split_flagged_pairs":12,
        "raw_private_inputs_replayed": injected is not None,"human_reviews_completed":0,
        "semantic_review_complete":False,"formal_readiness_evidence":False,
        "warning":"Source IDs and views are not certified independent samples; risk pairs are not proven duplicates. Prior Git asset inventory is not content review."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injected", type=Path)
    parser.add_argument("--natural-root", type=Path)
    parser.add_argument("--prepare-private-out", type=Path)
    args = parser.parse_args()
    if (args.injected is None) != (args.natural_root is None):
        parser.error("Both --injected and --natural-root are required for private replay")
    if args.prepare_private_out:
        if args.injected is None:
            parser.error("Private inputs required for preparation")
        prepare(args.injected, args.natural_root, args.prepare_private_out)
    result = audit(args.injected, args.natural_root)
    name = "private-replay-verification.json" if args.injected else "verification.json"
    (ROOT / name).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2))
