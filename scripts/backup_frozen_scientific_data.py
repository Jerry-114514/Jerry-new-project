"""Copy only protocol-bound scientific files; never interpret labels or run models.

This archive is PRIVATE while formal evaluations are unfinished. Creating or
verifying it is not permission to publish it, and does not certify data quality.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_lock(path, expected_lock):
    raw = Path(path).read_bytes()
    lock = json.loads(raw)
    body = {k: v for k, v in lock.items() if k != 'lock_hash'}
    actual = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()
    if actual != expected_lock or lock['lock_hash'] != expected_lock:
        raise ValueError('Protocol lock identity mismatch')
    return raw, lock


def members_for(lock, lock_path):
    """Explicit allowlist, not a recursive directory copy or arbitrary traversal."""
    dataset = lock['spec']['dataset']
    data_root = PurePosixPath(dataset['tasks']).parent
    export_root = data_root / 'export'
    if str(export_root) != dataset['export'] or str(export_root) != lock['dataset_export']['root']:
        raise ValueError('Inconsistent export root')
    result = {}

    def add(alias, path, checksum):
        if alias in result or len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
            raise ValueError('Duplicate member or invalid SHA256')
        result[alias] = {'source': str(path), 'sha256': checksum}

    for key, filename in [('cases', 'cases.jsonl'), ('tasks', 'tasks.jsonl'),
                          ('references', 'references.jsonl'), ('labels', 'export/programmatic-labels.jsonl')]:
        bound = lock['annotation_inputs'][key]
        wanted = str(data_root / filename)
        if bound['path'] != wanted or dataset[key] != wanted:
            raise ValueError('Inconsistent annotation input binding')
        if key != 'labels':
            add('dataset/' + filename, wanted, bound['sha256'])
        elif bound['sha256'] != lock['dataset_export']['files_sha256']['programmatic-labels.jsonl']:
            raise ValueError('Inconsistent label hash')
    expected_exports = {'train.jsonl', 'validation.jsonl', 'manifest.json', 'programmatic-labels.jsonl',
                        'heldout/test/cases.jsonl', 'heldout/test/gold.jsonl',
                        'heldout/ood/cases.jsonl', 'heldout/ood/gold.jsonl'}
    exported = lock['dataset_export']['files_sha256']
    if set(exported) != expected_exports:
        raise ValueError('Unexpected export members; review before copying')
    for name in sorted(expected_exports):
        add('dataset/export/' + name, export_root / name, exported[name])
    for key, filename in [('tasks', 'execution-tasks.jsonl'), ('references', 'execution-references.jsonl')]:
        bound = lock['execution_binding']['files'][key]
        wanted = str(data_root / filename)
        if bound['path'] != wanted or lock['spec']['execution'][key] != wanted:
            raise ValueError('Inconsistent execution binding')
        add('dataset/' + filename, wanted, bound['sha256'])
    add('protocol/formal-protocol.lock.json', lock_path, sha_file(lock_path))
    return result


def verify(archive, lock_path, expected_lock, expected_archive):
    raw, lock = read_lock(lock_path, expected_lock)
    expected = members_for(lock, lock_path)
    archive_sha = sha_file(archive)
    if archive_sha != expected_archive:
        raise ValueError('Archive SHA256 mismatch')
    sizes = {}
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            if member.name not in expected or member.name in sizes or not member.isfile():
                raise ValueError('Unexpected, duplicate or nonregular archive member')
            stream = tar.extractfile(member)
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != expected[member.name]['sha256']:
                raise ValueError('Bound scientific member SHA256 mismatch')
            sizes[member.name] = member.size
    if set(sizes) != set(expected):
        raise ValueError('Missing scientific member')
    return {'kind': 'verified_private_frozen_scientific_data_backup',
            'protocol_hash': expected_lock, 'archive_sha256': archive_sha,
            'archive_bytes': Path(archive).stat().st_size,
            'protocol_file_sha256': hashlib.sha256(raw).hexdigest(),
            'members': {name: {'sha256': expected[name]['sha256'], 'bytes': sizes[name]}
                        for name in sorted(sizes)},
            'member_count': len(sizes), 'uncompressed_bytes': sum(sizes.values()),
            'label_bytes_copied_and_hashed': True, 'labels_interpreted': False,
            'model_called': False, 'public_release_authorized_by_this_receipt': False,
            'semantic_independence_certified': False, 'm8_complete': False}


def create(lock_path, expected_lock, out):
    _, lock = read_lock(lock_path, expected_lock)
    members = members_for(lock, lock_path)
    # Validate the entire source set before reserving an output directory.
    for item in members.values():
        source = Path(item['source'])
        if not source.is_file() or source.is_symlink() or any(p.is_symlink() for p in source.parents):
            raise ValueError('Scientific source is missing, nonregular or symlinked')
        if sha_file(source) != item['sha256']:
            raise ValueError('Frozen scientific source changed')
    out = Path(out)
    out.mkdir(parents=False, exist_ok=False)
    archive = out / 'frozen-scientific-data.tar.gz'
    with tarfile.open(archive, 'x:gz', compresslevel=1, format=tarfile.PAX_FORMAT) as tar:
        for name, item in sorted(members.items()):
            tar.add(item['source'], arcname=name, recursive=False)
    receipt = verify(archive, lock_path, expected_lock, sha_file(archive))
    # Check source bytes again after the copy, including the lock itself.
    if any(sha_file(item['source']) != item['sha256'] for item in members.values()):
        raise ValueError('Scientific source changed during copy')
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['create', 'verify'])
    parser.add_argument('--lock', required=True, type=Path)
    parser.add_argument('--expected-lock', required=True)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--expected-sha256')
    args = parser.parse_args()
    if args.action == 'create':
        if args.out is None or args.archive is not None or args.expected_sha256 is not None:
            parser.error('create requires --out only')
        result = create(args.lock, args.expected_lock, args.out)
    else:
        if args.archive is None or args.expected_sha256 is None or args.out is not None:
            parser.error('verify requires --archive and trusted --expected-sha256 only')
        result = verify(args.archive, args.lock, args.expected_lock, args.expected_sha256)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
