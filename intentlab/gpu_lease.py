"""Process-scoped exclusive CUDA use for the single-GPU experiment host.

Kernel file locks, not stale PID files, decide ownership. Legacy/external
programs cannot be forced to cooperate; active CUDA processes are also checked.
"""

import atexit
import json
import os
from pathlib import Path
import subprocess
import tempfile


class GpuBusy(RuntimeError):
    pass


def compute_processes():
    try:
        result = subprocess.run(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, check=True, timeout=10)
        return {int(line.strip()) for line in result.stdout.splitlines() if line.strip()}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise GpuBusy("Cannot verify CUDA occupancy with nvidia-smi; no model was loaded") from exc


class GpuLease:
    def __init__(self, path=None, probe=None):
        self.path = Path(path or ("/tmp/intentlab-cuda.lease" if os.name == "posix" else Path(tempfile.gettempdir()) / "intentlab-cuda.lease"))
        self.probe = probe or compute_processes
        self.handle = None
        self.owner_pid = None

    def acquire(self):
        if self.handle is not None:
            if self.owner_pid != os.getpid():
                raise GpuBusy("Inherited lease does not authorize a forked child")
            return self
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, 0o600)
        os.set_inheritable(fd, False)
        handle = os.fdopen(fd, "r+b", buffering=0)
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b" ")  # Windows locks byte zero; metadata begins at one.
        handle.seek(0)
        try:
            if os.name == "posix":
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                raise GpuBusy("Unsupported GPU lease platform")
        except OSError as exc:
            handle.close()
            raise GpuBusy("Another managed CUDA experiment owns the GPU lease; no model was loaded") from exc
        except BaseException:
            handle.close()
            raise
        self.handle, self.owner_pid = handle, os.getpid()
        try:
            self.assert_available()
            handle.seek(1)
            handle.write(json.dumps({"pid": self.owner_pid, "kind": "process_scoped_cuda_lease"}).encode("utf-8"))
            handle.truncate()
        except BaseException:
            self.release()
            raise
        return self

    def assert_available(self):
        if self.handle is None or self.owner_pid != os.getpid():
            raise GpuBusy("CUDA process does not own the experiment lease")
        foreign = self.probe() - {os.getpid()}
        if foreign:
            raise GpuBusy("Other CUDA compute processes are active (PIDs " + ",".join(map(str, sorted(foreign))) + "); stop this launch before loading/generating")

    def release(self):
        if self.handle is None:
            return
        handle, owner = self.handle, self.owner_pid
        self.handle, self.owner_pid = None, None
        try:
            if owner == os.getpid():
                handle.seek(0)
                if os.name == "posix":
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_UN)
                elif os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            handle.close()
        # Never unlink: removing an open lock file permits a second lock inode.

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.release()


_process_lease = None


def ensure_gpu_lease():
    global _process_lease
    if _process_lease is not None and _process_lease.owner_pid != os.getpid():
        _process_lease.release()  # Child closes its inherited FD without unlocking parent.
        _process_lease = None
    if _process_lease is None:
        lease = GpuLease().acquire()
        _process_lease = lease
        atexit.register(lease.release)
    else:
        _process_lease.assert_available()
    return _process_lease
