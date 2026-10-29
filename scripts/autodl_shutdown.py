"""Invoke the fixed AutoDL shutdown file, including a validated ENOEXEC fallback.

Callers must first stop owned work and preserve required outputs. A returned
zero never proves provider billing stopped. No guard clocks are changed here.
"""
import errno
from pathlib import Path
import subprocess
import sys


def _invoke(official,timeout=30):
    official=Path(official)
    command_path=official.as_posix()
    try:
        completed=subprocess.run([command_path],capture_output=True,text=True,timeout=timeout)
        method='direct'
    except OSError as exc:
        if exc.errno!=errno.ENOEXEC:raise
        raw=official.read_bytes()
        if not official.is_file() or not 0<len(raw)<65536 or b'\0' in raw:
            raise ValueError('Official shutdown file is not a bounded text script') from exc
        try:raw.decode('utf-8')
        except UnicodeError as bad:raise ValueError('Official shutdown script is not UTF-8') from bad
        syntax=subprocess.run(['/bin/bash','-n',command_path],capture_output=True,text=True,timeout=10)
        if syntax.returncode!=0:raise ValueError('Official shutdown file did not pass Bash syntax validation')
        completed=subprocess.run(['/bin/bash',command_path],capture_output=True,text=True,timeout=timeout)
        method='validated_bash_after_enoexec'
    return {'method':method,'returncode':completed.returncode,'provider_stop_verified':False}


def request_shutdown():
    """Use only the documented provider path; never interpret shell command text."""
    if sys.platform!='linux':raise ValueError('AutoDL instance shutdown is Linux-only')
    return _invoke('/usr/bin/shutdown')
