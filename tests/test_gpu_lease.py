import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from intentlab.gpu_lease import GpuBusy, GpuLease, compute_processes


class GpuLeaseTests(unittest.TestCase):
    def test_competing_process_refused_and_crash_releases_kernel_lock(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "gpu.lease"
            script = (
                "from intentlab.gpu_lease import GpuLease; import sys; "
                "lease=GpuLease(sys.argv[1],probe=lambda:set()).acquire(); "
                "print('acquired',flush=True); sys.stdin.readline()")
            child = subprocess.Popen([sys.executable, "-u", "-c", script, str(path)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), "acquired")
                with self.assertRaises(GpuBusy):
                    GpuLease(path, probe=lambda: set()).acquire()
                child.kill()
                child.communicate(timeout=10)
                # No stale PID deletion or lock-file unlinking is needed.
                self.assertTrue(path.exists())
                with GpuLease(path, probe=lambda: set()):
                    pass
            finally:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=10)

    def test_legacy_foreign_cuda_refused_and_failed_probe_releases_lock(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "gpu.lease"
            with self.assertRaises(GpuBusy):
                GpuLease(path, probe=lambda: {os.getpid(), os.getpid() + 1}).acquire()
            with GpuLease(path, probe=lambda: {os.getpid()}) as lease:
                lease.probe = lambda: {os.getpid() + 1}
                with self.assertRaises(GpuBusy):
                    lease.assert_available()
            with GpuLease(path, probe=lambda: set()):
                pass

    def test_probe_failures_do_not_mean_idle(self):
        with patch("intentlab.gpu_lease.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaises(GpuBusy):
                compute_processes()
        with patch("intentlab.gpu_lease.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "not-a-pid\n", "")):
            with self.assertRaises(GpuBusy):
                compute_processes()
        with patch("intentlab.gpu_lease.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "12\n34\n12\n", "")):
            self.assertEqual(compute_processes(), {12, 34})

    def test_cuda_entries_refuse_before_ml_import_or_model_loading(self):
        from intentlab.model_backend import LocalBackend
        from intentlab.model_pool import LocalModelPool
        from intentlab.neural import train_neural
        with patch("intentlab.model_backend.ensure_gpu_lease", side_effect=GpuBusy("occupied")), \
             patch("intentlab.model_backend.dependencies") as dependencies:
            with self.assertRaises(GpuBusy):
                LocalBackend("never-load", "cuda")
            dependencies.assert_not_called()
        with patch("intentlab.model_pool.ensure_gpu_lease", side_effect=GpuBusy("occupied")):
            with self.assertRaises(GpuBusy):
                LocalModelPool({"actor": "never-load"}, "cuda")
        with patch("intentlab.gpu_lease.ensure_gpu_lease", side_effect=GpuBusy("occupied")), \
             patch("intentlab.neural.dependencies") as dependencies:
            with self.assertRaises(GpuBusy):
                train_neural({"device": "cuda"}, Path("never-create"))
            dependencies.assert_not_called()

    def test_same_process_can_reuse_lease_and_release_is_idempotent(self):
        with tempfile.TemporaryDirectory() as name:
            lease = GpuLease(Path(name) / "gpu.lease", probe=lambda: set())
            self.assertIs(lease.acquire(), lease.acquire())
            lease.release()
            lease.release()
            self.assertTrue(lease.path.exists())


if __name__ == "__main__":
    unittest.main()
