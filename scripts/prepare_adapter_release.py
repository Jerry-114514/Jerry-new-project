"""Prepare six hash-bound inference exports locally; never publish or bill storage."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

JOBS = [f'{schedule}-seed-{seed}' for schedule in ('cosine', 'plateau') for seed in range(3)]
ASSETS = {'adapter_model.safetensors', 'adapter_config.json', 'selection.json', 'chat_template.jinja',
          'tokenizer.json', 'tokenizer_config.json'}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def bound_json(path, expected):
    if not isinstance(expected, str) or len(expected) != 64 or sha(path) != expected:
        raise ValueError('Input differs from previously trusted SHA256')
    return json.loads(Path(path).read_text(encoding='utf-8'))


def prepare(plan_path, plan_sha, receipt_path, receipt_sha, out):
    plan = bound_json(plan_path, plan_sha)
    receipt = bound_json(receipt_path, receipt_sha)
    if receipt['kind'] != 'completed_formal_training_matrix_receipt' or receipt['completed_jobs'] != 6 \
            or receipt['off_host_verified_backups'] != 6 or set(receipt['selections']) != set(JOBS):
        raise ValueError('All six completed, independently backed-up selected jobs required')
    wanted = {f'endpoints/{job}/model/{name}': f'{job}/{name}' for job in JOBS for name in ASSETS}
    rows = {}
    for item in plan['files']:
        if item['path'] not in wanted:
            continue
        if item['path'] in rows:
            raise ValueError('Duplicate source asset')
        source = Path(item['source'])
        if not source.is_file() or any(p.is_symlink() for p in (source, *source.parents)) \
                or source.stat().st_size != item['bytes'] or sha(source) != item['sha256']:
            raise ValueError('Restored source asset bytes changed')
        rows[item['path']] = item
    if set(rows) != set(wanted):
        raise ValueError('Exact allowlisted inference exports required')
    for job in JOBS:
        weight = rows[f'endpoints/{job}/model/adapter_model.safetensors']
        selected = receipt['selections'][job]
        if selected['export_files_sha256']['adapter_model.safetensors'] != weight['sha256']:
            raise ValueError('Weights differ from the published validation-selected checkpoint')
    out = Path(out)
    # Do not copy back into any source subtree or overwrite previous packages.
    if out.exists() or any(out.resolve().is_relative_to(Path(item['source']).resolve().parent) for item in rows.values()):
        raise ValueError('Fresh output directory outside source exports required')
    out.mkdir(parents=True, exist_ok=False)
    files = {}
    for name, destination in sorted(wanted.items()):
        item = rows[name]
        target = out / destination
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(item['source'], target)
        if target.stat().st_size != item['bytes'] or sha(target) != item['sha256'] or sha(item['source']) != item['sha256']:
            raise ValueError('Source changed during copy or destination bytes differ')
        files[destination] = {'sha256': item['sha256'], 'bytes': item['bytes']}
    (out / '.gitattributes').write_text('*/adapter_model.safetensors filter=lfs diff=lfs merge=lfs -text\n', encoding='utf-8')
    (out / 'README.md').write_text(
        '# Selected Qwen3.5-9B LoRA inference exports\n\n'
        'This is a locally prepared package, not proof of a public upload or completed M8. '
        'The manifest binds the original validation-selected exports. All six seeds/schedules are retained.\n\n'
        'Only inference assets are included; no base weights, optimizer checkpoint, test cases or gold. '
        'The source adapter configurations are byte-identical and may name the old server base path. '
        'Always load the official base explicitly, then attach the chosen local adapter.\n\n'
        'Official base: Qwen/Qwen3.5-9B; revision: `' + plan['official_revision'] + '`.\n\n'
        '```python\nimport torch\nfrom transformers import AutoModelForCausalLM, AutoTokenizer\n'
        'from peft import PeftModel\nadapter_path = "PATH/cosine-seed-0"\n'
        'base = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3.5-9B",\n'
        '    revision="' + plan['official_revision'] + '", dtype=torch.bfloat16, trust_remote_code=False)\n'
        'model = PeftModel.from_pretrained(base, adapter_path, is_trainable=False).to("cuda").eval()\n'
        'tokenizer = AutoTokenizer.from_pretrained(adapter_path, local_files_only=True, trust_remote_code=False)\n```\n\n'
        'Training used NF4 QLoRA; formal inference loaded the base in BF16 plus LoRA. '
        'This package preparation checks bytes, not model loading, quality or inference memory. '
        'Labels are programmatic under explicitly encoded specifications; no human evaluation is claimed.\n\n'
        'If later published with Git LFS, disable automatic smudging on initial clone and fetch only the needed '
        'adapter to avoid downloading all six. Account LFS usage and overage controls must be checked before upload.\n',
        encoding='utf-8')
    manifest = {'kind': 'prepared_selected_adapter_release', 'status': 'prepared_not_uploaded',
                'protocol_hash': receipt['protocol_hash'], 'binding_hash': receipt['binding_hash'],
                'official_revision': plan['official_revision'], 'training_receipt_sha256': receipt_sha,
                'selected_steps': {job: receipt['selections'][job]['step'] for job in JOBS},
                'files': files, 'file_count': len(files), 'bytes': sum(v['bytes'] for v in files.values()),
                'adapter_weight_bytes': sum(v['bytes'] for name, v in files.items() if name.endswith('.safetensors')),
                'base_weights_included': False, 'optimizer_or_pickle_included': False,
                'test_material_included': False, 'model_forward_verified_by_preparation': False,
                'public_upload_performed': False, 'm8_complete': False}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'training-receipt', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--receipt-sha256', required=True)
    args = parser.parse_args()
    result = prepare(args.plan, args.plan_sha256, args.training_receipt, args.receipt_sha256, args.out)
    print(json.dumps({k: result[k] for k in ('status', 'file_count', 'bytes', 'adapter_weight_bytes', 'public_upload_performed')}))


if __name__ == '__main__':
    main()
