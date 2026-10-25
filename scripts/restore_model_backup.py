"""Restore a trusted model bundle to a fresh directory without loading a model or pickle."""
import argparse
import json
from pathlib import Path, PureWindowsPath
import shutil
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.model_backup import file_sha, safe_name, verify_model_backup


def restore(archive, expected_sha256, out):
    archive, out = Path(archive).resolve(), Path(out).absolute()
    if len(expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError('A previously recorded source SHA256 is required')
    verification = verify_model_backup(archive, expected_sha256)
    # Check Windows aliases on every platform so the same bundle is portable.
    with tarfile.open(archive, 'r:') as handle:
        members = handle.getmembers()
        names = set()
        for member in members:
            safe_name(member.name)
            parts = member.name.split('/')
            if any(p.endswith((' ', '.')) or PureWindowsPath(p).is_reserved() for p in parts):
                raise ValueError('Nonportable model bundle path')
            key = member.name.casefold()
            if key in names:
                raise ValueError('Case-insensitive bundle path collision')
            names.add(key)
        if any('/'.join(name.split('/')[:i]) in names
               for name in names for i in range(1, len(name.split('/')))):
            raise ValueError('Bundle file/directory collision')
    # An existing output is never reused; failed copies remain available for inspection.
    out.mkdir(parents=True, exist_ok=False)
    payload = out / 'payload'
    payload.mkdir()
    receipt = {'kind': 'model_bundle_filesystem_restore', 'status': 'restoring',
               'archive_sha256': expected_sha256, 'verification': verification,
               'model_or_pickle_loaded': False, 'model_inference_verified': False,
               'training_resume_verified': False, 'm8_complete': False}
    def save():
        (out / 'restore-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    save()
    try:
        with tarfile.open(archive, 'r:') as handle:
            index = json.load(handle.extractfile('backup-index.json'))
            # Use only prevalidated names, never extractall or archive-provided links.
            for member in members:
                target = payload / member.name
                if not target.resolve().is_relative_to(payload.resolve()):
                    raise ValueError('Restore target escaped payload directory')
                target.parent.mkdir(parents=True, exist_ok=True)
                with handle.extractfile(member.name) as source, target.open('xb') as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
        restored = {}
        for name, record in index['files'].items():
            path = payload / name
            actual = {'bytes': path.stat().st_size, 'sha256': file_sha(path)}
            if actual != record:
                raise ValueError('Restored bytes differ from source inventory: ' + name)
            restored[name] = actual
        actual_names = {p.relative_to(payload).as_posix() for p in payload.rglob('*') if p.is_file()}
        if actual_names != set(index['files']) | {'backup-index.json'}:
            raise ValueError('Unexpected restored file inventory')
        if file_sha(archive) != expected_sha256:
            raise ValueError('Archive changed during restore')
        receipt.update(status='completed', restored_files=restored,
                       restored_source_bytes=sum(r['bytes'] for r in restored.values()))
    except BaseException as exc:
        receipt.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        save()
        raise
    save()
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = restore(args.archive, args.expected_sha256, args.out)
    print(json.dumps({key: result[key] for key in ('status', 'restored_source_bytes', 'model_or_pickle_loaded', 'm8_complete')}))
