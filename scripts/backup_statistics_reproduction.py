"""Archive completed statistics and their replay; never certify full M8.

Inputs must be bound to a previously observed supervisor SHA and driver SHA.
This copies existing statistics only: no model, gold, tuning or new analysis.
The caller must transfer the archive off host and verify it there separately.
"""
import argparse
import json
from pathlib import Path
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_restored_inference import completed_statistics, digest, read, sha


def inventory(roots):
    result = {}
    for prefix, root in roots.items():
        paths = [root, *root.parents, *root.rglob('*')]
        if not root.is_dir() or any(p.is_symlink() for p in paths):
            raise ValueError('Missing or symlinked statistics directory')
        for path in sorted(root.rglob('*')):
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError('Nonregular statistics member')
            name = prefix + '/' + path.relative_to(root).as_posix()
            result[name] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
    return result


def verify_archive(archive, expected):
    archive = Path(archive)
    if sha(archive) != expected['archive_sha256'] or archive.stat().st_size != expected['archive_bytes']:
        raise ValueError('Statistics archive differs from trusted receipt')
    seen = set()
    with tarfile.open(archive, 'r:') as tar:
        for member in tar:
            if not member.isfile() or member.name in seen or member.name not in expected['files']:
                raise ValueError('Unexpected or duplicate statistics archive member')
            bound = expected['files'][member.name]
            import hashlib
            with tar.extractfile(member) as stream:
                checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            if member.size != bound['bytes'] or checksum != bound['sha256']:
                raise ValueError('Statistics archive member changed')
            seen.add(member.name)
    if seen != set(expected['files']):
        raise ValueError('Missing statistics archive member')
    return {'verified_members': len(seen), 'all_archive_members_reverified': True,
            'archive_sha256': expected['archive_sha256'], 'm8_complete': False}


def create(supervision, analysis, replay, expected_status, expected_driver, protocol, binding, out, identity=None):
    roots = {name: Path(path).resolve() for name, path in
             [('supervision', supervision), ('analysis', analysis), ('replay', replay)]}
    # Reject symlink roots before resolve(), including their parent components.
    for path in map(Path, (supervision, analysis, replay)):
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Symlinked statistics root')
    if len(set(roots.values())) != 3 or any(a != b and a.is_relative_to(b)
            for a in roots.values() for b in roots.values()):
        raise ValueError('Distinct, nonnested source directories required')
    out = Path(out)
    if any(out.resolve().is_relative_to(root) for root in roots.values()):
        raise ValueError('Archive output must be outside source directories')
    if identity is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from intentlab.gpu_lease import process_identity
        identity = process_identity
    before = inventory(roots)
    status_path = roots['supervision'] / 'supervisor-status.json'
    status = completed_statistics(status_path, expected_status, identity)
    if status['driver_sha256'] != expected_driver or status['protocol_hash'] != protocol \
            or status['binding_hash'] != binding or status['m8_complete'] is not False:
        raise ValueError('Statistics supervisor identity mismatch')
    claim = read(roots['supervision'] / 'supervisor.claim.json')
    if any(claim[k] != status[k] for k in ('pid', 'start_ticks', 'driver_sha256', 'started_unix',
                                          'runtime_commit', 'protocol_hash', 'binding_hash')):
        raise ValueError('Statistics claim does not identify completed supervisor')
    reports, manifests = [], []
    for name, expected_receipt in [('analysis', status['statistics_receipt_hash']),
                                   ('replay', status['replay_receipt_hash'])]:
        root = roots[name]
        manifest = read(root / 'manifest.json')
        if manifest['kind'] != 'frozen_statistics_analysis' or manifest['scope'] != 'formal' \
                or manifest['status'] != 'completed' or manifest['m8_complete'] is not False \
                or manifest['gold_or_references_reopened'] is not False \
                or manifest['protocol_hash'] != protocol or manifest['model_binding_hash'] != binding \
                or manifest['receipt_hash'] != expected_receipt \
                or digest({k:v for k,v in manifest.items() if k!='receipt_hash'}) != expected_receipt:
            raise ValueError('Incomplete or changed statistics manifest')
        actual = inventory({name:root})
        actual = {k[len(name)+1:]:v['sha256'] for k,v in actual.items() if k != name+'/manifest.json'}
        if actual != manifest['files_sha256'] or 'report.json' not in actual:
            raise ValueError('Statistics sealed files differ')
        report = read(root / 'report.json')
        if report['scope'] != 'formal' or report['protocol_hash'] != protocol \
                or report['m8_complete'] is not False or len(report['comparisons']) != 18 \
                or report['secondary_family_size'] != 17:
            raise ValueError('Registered comparison population differs')
        reports.append(report)
        manifests.append(manifest)
    if digest(reports[0]) != digest(reports[1]) or digest(reports[0]) != status['report_content_digest'] \
            or manifests[0]['upstream_receipts'] != manifests[1]['upstream_receipts'] \
            or manifests[0]['upstream_receipts']['M7'] != status['ablation_receipt_hash']:
        raise ValueError('Original and replay statistics disagree')
    if before != inventory(roots):
        raise ValueError('Statistics changed during admission')
    out.mkdir(exist_ok=False)
    archive = out / 'sealed-statistics.tar'
    with tarfile.open(archive, 'x', format=tarfile.PAX_FORMAT) as tar:
        for name in before:
            prefix, relative = name.split('/',1)
            tar.add(roots[prefix] / relative, arcname=name, recursive=False)
    if before != inventory(roots):
        raise ValueError('Statistics changed during archival; preserve failed archive')
    receipt = {'kind':'completed_statistics_reproduction_backup','protocol_hash':protocol,
               'binding_hash':binding,'supervisor_status_sha256':expected_status,'driver_sha256':expected_driver,
               'archive_sha256':sha(archive),'archive_bytes':archive.stat().st_size,'files':before,
               'report_content_digest':status['report_content_digest'],
               'canonical_reports_identical':True,'m8_complete':False,
               'off_host_copy_verified':False,'scientific_assumptions_certified':False}
    receipt['local_archive_verification'] = verify_archive(archive, receipt)
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('supervision','analysis','replay','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    for name in ('expected-status','expected-driver','protocol','binding'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    result=create(args.supervision,args.analysis,args.replay,args.expected_status,args.expected_driver,
                  args.protocol,args.binding,args.out)
    print(json.dumps({k:result[k] for k in ('kind','archive_sha256','archive_bytes','m8_complete')}))


if __name__=='__main__':main()
