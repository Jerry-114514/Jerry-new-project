"""Post-experiment BF16 load/forward smoke check from restored inference assets.

This is a recovery check on a fixed public prompt, not a new scientific model
evaluation, training resume, bitwise reproduction or replacement for M8 audit.
All model loads explicitly use the restored base; embedded old base paths are
recorded but never used. Run only after original statistics supervision ends.
"""
import argparse
import gc
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import platform
import subprocess
import sys
import time

JOBS = [f'{schedule}-seed-{seed}' for schedule in ('cosine', 'plateau') for seed in range(3)]
PROMPT = 'Return exactly one JSON object with a single key count and integer value 2. No other text.'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def completed_statistics(path, expected_sha, identity):
    if sha(path) != expected_sha:
        raise ValueError('Statistics supervision differs from previously observed trusted SHA256')
    status = read(path)
    if status['kind'] != 'frozen_statistics_reproduction_supervisor' or status['status'] != 'completed' \
            or status['statistics_reproduction_complete'] is not True or status['canonical_reports_identical'] is not True \
            or [s['action'] for s in status['stages']] != ['analysis', 'verify', 'replay', 'verify-replay'] \
            or any(s['status'] != 'completed' or type(s['exit_code']) is not int or s['exit_code'] != 0
                   for s in status['stages']):
        raise ValueError('Original statistics supervision must complete before model recovery inference')
    if identity(status['pid']).get('proc_visible') or any(
            identity(stage['child_pid']).get('proc_visible') for stage in status['stages']):
        raise ValueError('Original statistics supervisor and workers must have exited')
    return status


def assets(root, expected_plan_digest):
    root = Path(root)
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError('Symlinked restore root rejected')
    root = root.resolve()
    plan = read(root / 'transfer-plan.json')
    if digest(plan) != expected_plan_digest or Path(plan['remote_root']).resolve() != root:
        raise ValueError('Restored assets differ from trusted pre-transfer plan')
    expected = {}
    for item in plan['files']:
        name = PurePosixPath(item['path'])
        if name.is_absolute() or '..' in name.parts or str(name) != item['path'] \
                or '\\' in item['path'] or ':' in item['path'] or item['path'] in expected \
                or not item['path'].startswith(('base/', 'endpoints/')):
            raise ValueError('Unsafe or duplicate restored asset path')
        path = root / item['path']
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file() \
                or type(item['bytes']) is not int or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise ValueError('Restored asset bytes differ from trusted plan')
        expected[item['path']] = item
    paths = list(root.rglob('*'))
    if any(path.is_symlink() for path in paths) or {p.relative_to(root).as_posix() for p in paths if p.is_file()} \
            != set(expected) | {'transfer-plan.json', 'restore-receipt.json'}:
        raise ValueError('Unexpected or missing restored files')
    if len(expected) != plan['file_count'] or sum(row['bytes'] for row in expected.values()) != plan['total_bytes']:
        raise ValueError('Restored plan cardinality mismatch')
    for job in JOBS:
        for name in ('adapter_config.json', 'adapter_model.safetensors', 'tokenizer.json', 'tokenizer_config.json'):
            if f'endpoints/{job}/model/{name}' not in expected:
                raise ValueError('All six selected inference exports required')
        config = read(root / 'endpoints' / job / 'model/adapter_config.json')
        if config.get('peft_type') != 'LORA' or config.get('bias', 'none') != 'none' \
                or config.get('modules_to_save') or config.get('layer_replication'):
            raise ValueError('Only non-base-mutating LoRA adapters supported')
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'source', 'protocol', 'statistics-status', 'budget-config', 'budget-status', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('source-commit', 'protocol-hash', 'expected-plan-digest', 'statistics-status-sha256', 'budget-config-sha256'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    if args.out.exists() or args.out.resolve().is_relative_to(args.root.resolve()):
        raise ValueError('Fresh output directory outside restored payload required')
    source = args.source.resolve()
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != args.source_commit \
            or subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain']):
        raise ValueError('Frozen inference source must be clean and unchanged')
    sys.path.insert(0, str(source))
    from intentlab.gpu_lease import ensure_gpu_lease, process_identity
    from intentlab.prompts import prompt_ids
    stats = completed_statistics(args.statistics_status, args.statistics_status_sha256, process_identity)
    protocol = read(args.protocol)
    if protocol['scope'] != 'formal' or protocol['lock_hash'] != args.protocol_hash \
            or digest({k: v for k, v in protocol.items() if k != 'lock_hash'}) != args.protocol_hash \
            or stats['protocol_hash'] != args.protocol_hash or stats['runtime_commit'] != args.source_commit:
        raise ValueError('Frozen source/protocol/statistics identity mismatch')
    environment = protocol['environment']
    if platform.python_version() != environment['python'] or any(
            importlib.metadata.version(name) != version for name, version in environment['packages'].items()):
        raise ValueError('Runtime packages differ from formal freeze')

    def budget():
        guard = read(args.budget_status)
        actual = process_identity(guard['pid'])
        if sha(args.budget_config) != args.budget_config_sha256 or guard['config_sha256'] != args.budget_config_sha256 \
                or guard['status'] != 'monitoring' or actual.get('start_ticks') != guard['start_ticks'] \
                or not 0 <= time.time() - guard['unix'] < 120 or guard['remaining_operating_seconds'] < 3600:
            raise ValueError('Original budget guard must remain live, fresh and unchanged with sufficient time')
    budget()
    plan = assets(args.root, args.expected_plan_digest)
    budget()
    ensure_gpu_lease()  # No model/torch load before completion, assets and occupancy checks.
    import torch
    import transformers
    from peft import PeftModel, get_peft_model_state_dict
    from safetensors.torch import load_file
    torch.set_num_threads(2)
    torch.manual_seed(0)
    if not torch.cuda.is_available() or '5090' not in torch.cuda.get_device_name(0):
        raise ValueError('Original RTX 5090 CUDA device required')
    args.out.mkdir(parents=True, exist_ok=False)
    state = {'kind': 'restored_selected_inference_smoke', 'status': 'running', 'pid': __import__('os').getpid(),
             'source_commit': args.source_commit, 'protocol_hash': args.protocol_hash,
             'probe_driver_sha256': sha(__file__), 'formal_inference_source_unchanged': True,
             'statistics_receipt_hash': stats['statistics_receipt_hash'], 'plan_digest': args.expected_plan_digest,
             'asset_files': plan['file_count'], 'asset_bytes': plan['total_bytes'], 'device': torch.cuda.get_device_name(0),
             'inference_dtype': 'bfloat16', 'quantization': None, 'training_state_loaded': False,
             'fixed_public_prompt': PROMPT, 'generations': [], 'm8_complete': False,
             'warning': 'Finite forward and bounded generation only; no training resume, formal quality score or original-output equivalence.'}
    def save():
        temp = args.out / 'status.pending.json'
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        temp.replace(args.out / 'status.json')
    save()
    model = None
    try:
        root = args.root.resolve()
        torch.cuda.reset_peak_memory_stats()
        base_path = root / 'base'
        model = transformers.AutoModelForCausalLM.from_pretrained(
            base_path, local_files_only=True, trust_remote_code=False, dtype=torch.bfloat16).to('cuda').eval()
        def probe(label, tokenizer):
            budget()
            ensure_gpu_lease()
            ids = prompt_ids(tokenizer, PROMPT)
            batch = torch.tensor([ids], device='cuda')
            with torch.inference_mode():
                logits = model(input_ids=batch, attention_mask=torch.ones_like(batch), use_cache=False, logits_to_keep=1).logits
                if not bool(torch.isfinite(logits).all()):
                    raise ValueError('Restored model produced nonfinite logits')
                del logits
                configured = model.generation_config.eos_token_id
                configured = list(configured) if isinstance(configured, (list, tuple)) else [configured]
                eos = list(dict.fromkeys(i for i in [tokenizer.eos_token_id] + configured if i is not None))
                generated = model.generate(input_ids=batch, attention_mask=torch.ones_like(batch),
                    max_new_tokens=8, do_sample=False, pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=eos or None)
            new_ids = generated[0, len(ids):].tolist()
            if not 1 <= len(new_ids) <= 8:
                raise ValueError('Restored model did not produce bounded nonempty generation')
            state['generations'].append({'model': label, 'prompt_token_ids': ids, 'new_token_ids': new_ids,
                                         'text': tokenizer.decode(new_ids, skip_special_tokens=True), 'finite_forward': True})
            save()
        probe('base', transformers.AutoTokenizer.from_pretrained(base_path, local_files_only=True, trust_remote_code=False))
        for index, job in enumerate(JOBS):
            adapter_path = root / 'endpoints' / job / 'model'
            budget()
            ensure_gpu_lease()
            if index == 0:
                model = PeftModel.from_pretrained(model, adapter_path, adapter_name=job, is_trainable=False, local_files_only=True)
            else:
                model.load_adapter(adapter_path, adapter_name=job, is_trainable=False, local_files_only=True)
            model.set_adapter(job, inference_mode=True)
            model.requires_grad_(False).eval()
            stored = load_file(str(adapter_path / 'adapter_model.safetensors'), device='cpu')
            loaded = get_peft_model_state_dict(model, adapter_name=job, save_embedding_layers=False)
            if set(stored) != set(loaded) or not stored or any(
                    not torch.equal(loaded[key].detach().cpu(), value) for key, value in stored.items()):
                raise ValueError('Loaded adapter tensors do not equal restored safetensors')
            del stored, loaded
            probe(job, transformers.AutoTokenizer.from_pretrained(adapter_path, local_files_only=True, trust_remote_code=False))
            model.delete_adapter(job)
        torch.cuda.synchronize()
        budget()
        state.update(status='completed', base_and_six_exports_loaded=True, finite_forward_count=7,
                     peak_allocated_bytes=torch.cuda.max_memory_allocated(), peak_reserved_bytes=torch.cuda.max_memory_reserved(),
                     embedded_old_base_paths_used=False)
        save()
    except BaseException as exc:
        state.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        save()
        raise
    finally:
        if model is not None:
            del model
        gc.collect()
        torch.cuda.empty_cache()


if __name__ == '__main__':
    main()
