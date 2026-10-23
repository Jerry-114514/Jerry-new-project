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
import time


class GpuBusy(RuntimeError):
    pass


def process_identity(pid):
    """Bounded diagnostic identity; never persist full arguments or environment."""
    info = {"pid": pid, "proc_visible": False}
    root = Path("/proc") / str(pid)
    try:
        fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
        info.update(proc_visible=True, start_ticks=fields[19], parent_pid=int(fields[1]))
        status = (root / "status").read_text()
        for line in status.splitlines():
            if line.startswith("Name:"):
                info["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("NSpid:"):
                info["namespace_pids"] = [int(value) for value in line.split()[1:]]
        info["executable_name"] = (root / "exe").resolve().name
        args = (root / "cmdline").read_bytes().decode(errors="replace").split("\0")
        if len(args) > 2 and args[1] == "-m":
            info["entry_module"] = args[2]
        elif len(args) > 1 and args[1].endswith(".py"):
            info["entry_script_name"] = Path(args[1]).name
    except (OSError, ValueError, IndexError):
        info["details_incomplete"] = True
    return info


def record_interference(foreign):
    destination = os.environ.get("INTENTLAB_CUDA_AUDIT_LOG")
    if not destination:
        return
    row = {"unix": time.time(), "observer": process_identity(os.getpid()),
           "foreign": [process_identity(pid) for pid in sorted(foreign)],
           "warning": "Different reported PIDs are not proof of independent jobs; inspect parent and namespace identities."}
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(destination, flags, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def reject_interfered_trial(record):
    """Resource admission failures cannot be interpreted as model performance.

    Older artifacts have message-only errors; retain support for those records
    so rehashing a historical interrupted trial cannot certify a fair selection.
    """
    for event in record.get("history", []):
        message = event.get("message", "")
        if event.get("phase") == "error" and (event.get("error_type") == "GpuBusy" or
                any(marker in message for marker in ("Other CUDA compute processes are active",
                    "Another managed CUDA experiment owns the GPU lease", "Cannot verify CUDA occupancy"))):
            raise GpuBusy("GPU resource interference invalidates this experiment; retain the failed trial and stop")


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
            diagnostic = ""
            try:
                record_interference(foreign)
            except OSError:
                diagnostic = "; diagnostic logging unavailable"
            raise GpuBusy("Other CUDA compute processes are active (PIDs " + ",".join(map(str, sorted(foreign))) + "); stop this launch before loading/generating" + diagnostic)

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
