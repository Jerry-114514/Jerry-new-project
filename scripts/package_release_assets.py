"""Build hash-verified GitHub Release attachments from prepared adapters; no LFS."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tarfile

from prepare_adapter_release import ASSETS, JOBS, sha

SHARED = {'tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja'}


def package(source, expected_manifest_sha, out):
    source, out = Path(source), Path(out)
    if out.exists() or sha(source / 'manifest.json') != expected_manifest_sha:
        raise ValueError('Fresh output and trusted prepared manifest required')
    original = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    expected = {job + '/' + name for job in JOBS for name in ASSETS}
    if set(original['files']) != expected or original['base_weights_included'] is not False \
            or original['optimizer_or_pickle_included'] is not False or original['test_material_included'] is not False:
        raise ValueError('Exact six selected inference exports required')
    for name, item in original['files'].items():
        path = source / name
        if any(p.is_symlink() for p in (path, *path.parents)) or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise ValueError('Prepared inference asset changed')
    for name in SHARED:
        if len({original['files'][job + '/' + name]['sha256'] for job in JOBS}) != 1:
            raise ValueError('Tokenizer sharing requires byte-identical files across all jobs')
    out.mkdir(parents=True, exist_ok=False)
    archives = {}
    def archive(filename, mapping):
        target = out / filename
        with target.open('xb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0, compresslevel=1) as zipped:
            with tarfile.open(fileobj=zipped, mode='w|', format=tarfile.USTAR_FORMAT) as tar:
                for member, relative in sorted(mapping.items()):
                    path = source / relative
                    info = tarfile.TarInfo(member)
                    info.size, info.mode, info.mtime = path.stat().st_size, 0o644, 0
                    with path.open('rb') as stream:
                        tar.addfile(info, stream)
        if target.stat().st_size >= 2 * 1024**3:
            raise ValueError('Release asset exceeds conservative 2 GiB bound')
        with tarfile.open(target, 'r:gz') as tar:
            members = tar.getmembers()
            if {m.name for m in members} != set(mapping) or len(members) != len(mapping) or any(not m.isfile() for m in members):
                raise ValueError('Archive member population changed')
            for member in members:
                with tar.extractfile(member) as stream:
                    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
                if actual != original['files'][mapping[member.name]]['sha256']:
                    raise ValueError('Archive bytes differ from selected inference export')
        archives[filename] = {'bytes': target.stat().st_size, 'sha256': sha(target), 'members': mapping}
    for job in JOBS:
        archive('qwen35-9b-' + job + '.tar.gz', {job + '/' + name: job + '/' + name for name in ASSETS - SHARED})
    archive('qwen35-9b-tokenizer.tar.gz', {'tokenizer/' + name: JOBS[0] + '/' + name for name in SHARED})
    manifest = {'kind': 'selected_adapter_release_assets', 'protocol_hash': original['protocol_hash'],
                'binding_hash': original['binding_hash'], 'official_revision': original['official_revision'],
                'training_receipt_sha256': original['training_receipt_sha256'], 'selected_steps': original['selected_steps'],
                'original_inference_files': original['files'], 'archives': archives, 'git_lfs_used': False,
                'model_loaded_by_packaging': False, 'm8_complete': False}
    (out / 'release-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    (out / 'README.md').write_text(
        '# Qwen3.5-9B validation-selected LoRA adapters\n\n'
        'Six M4 inference exports, retaining all cosine/plateau seeds 0/1/2. These are Release attachments, not Git LFS. '
        'Download one job archive plus the shared tokenizer archive and SHA256SUMS.txt.\n\n'
        '```bash\nsha256sum -c SHA256SUMS.txt --ignore-missing\n'
        'tar -xzf qwen35-9b-cosine-seed-0.tar.gz\n'
        'tar -xzf qwen35-9b-tokenizer.tar.gz --strip-components=1 -C cosine-seed-0\n```\n\n'
        'The original adapter config may contain the old server base path. Load the base explicitly:\n\n'
        '```python\nimport torch\nfrom transformers import AutoModelForCausalLM, AutoTokenizer\nfrom peft import PeftModel\n'
        'base = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3.5-9B",\n'
        '    revision="' + original['official_revision'] + '", dtype=torch.bfloat16, trust_remote_code=False)\n'
        'model = PeftModel.from_pretrained(base, "cosine-seed-0", is_trainable=False).to("cuda").eval()\n'
        'tokenizer = AutoTokenizer.from_pretrained("cosine-seed-0", local_files_only=True, trust_remote_code=False)\n```\n\n'
        'Training used NF4 QLoRA; formal inference used a BF16 base plus LoRA. Checkpoints were selected only by validation loss. '
        'Labels are programmatic under explicitly encoded specifications; no human evaluation or open-domain safety claim. '
        'No base weights, optimizer/pickle, heldout tasks or gold are included. Packaging verifies bytes; it does not certify '
        'model quality, interrupted training resume or complete M8 acceptance.\n', encoding='utf-8', newline='\n')
    sums = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    (out / 'SHA256SUMS.txt').write_text(''.join(value + '  ' + name + '\n' for name, value in sorted(sums.items())),
                                       encoding='utf-8', newline='\n')
    return {'assets': len(sums) + 1, 'archive_count': len(archives),
            'total_asset_bytes': sum(p.stat().st_size for p in out.iterdir()), 'git_lfs_used': False,
            'all_archive_members_reverified': True, 'uploaded': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.source, args.expected_manifest_sha256, args.out)))


if __name__ == '__main__':
    main()
