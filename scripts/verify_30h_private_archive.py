"""Verify private follow-up archive bytes and regular members without extraction."""
import hashlib
import json
from pathlib import Path,PurePosixPath
import tarfile


def verify(archive,expected_sha):
    archive=Path(archive)
    with archive.open('rb') as f:
        actual=hashlib.file_digest(f,'sha256').hexdigest()
    if actual!=expected_sha:raise ValueError('Private archive differs from captured source hash')
    with tarfile.open(archive,'r:*') as a:
        members=a.getmembers();names=[m.name for m in members]
        if len(names)!=len(set(names)) or any(not m.isfile() for m in members):raise ValueError('Nonregular or duplicate member')
        for name in names:
            p=PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or str(p)!=name or '\\' in name or ':' in name:raise ValueError('Unsafe member path')
        header=a.getmember('backup-index.json')
        if header.size>4*1024*1024:raise ValueError('Index too large')
        index=json.load(a.extractfile(header))
        if index.get('kind') not in ('private_limited_followup_data','unvalidated_partial_state') or set(names)!=set(index['files'])|{'backup-index.json'}:
            raise ValueError('Wrong private archive index or missing members')
        for name,row in index['files'].items():
            if a.getmember(name).size!=row['bytes'] or hashlib.file_digest(a.extractfile(name),'sha256').hexdigest()!=row['sha256']:
                raise ValueError('Private archive member differs from index')
    return {'archive_sha256':actual,'members':len(members),'kind':index['kind'],'all_member_hashes_verified':True,
            'extracted':False,'model_or_pickle_loaded':False}
