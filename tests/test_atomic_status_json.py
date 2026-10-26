import ctypes
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('atomic_status', ROOT / 'scripts/atomic_status_json.py')
atomic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(atomic)


class AtomicStatusTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'tmp'
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base, prefix='atomic-status-test-')
        self.root = Path(self.temp.name).resolve()
        assert self.root.is_relative_to(base.resolve())
        self.addCleanup(self.temp.cleanup)
        self.path = self.root / 'status.json'
        self.old = {'status': 'old', 'value': '旧状态'}
        atomic.atomic_json_dump(self.path, self.old)

    def test_unicode_and_serialization_failure_preserve_complete_journal(self):
        self.assertEqual(atomic.atomic_json_dump(self.path, {'status': '新状态'}), 1)
        self.assertEqual(json.loads(self.path.read_bytes()), {'status': '新状态'})
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            atomic.atomic_json_dump(self.path, {'value': float('nan')})
        self.assertEqual(self.path.read_bytes(), before)

    def test_bounded_conflict_keeps_old_json_and_pending_bytes(self):
        error = PermissionError('synthetic Windows sharing conflict')
        error.winerror = 5
        with patch.object(atomic.os, 'replace', side_effect=error) as replace, patch.object(atomic.time, 'sleep') as sleep:
            with self.assertRaises(PermissionError):
                atomic.atomic_json_dump(self.path, {'status': 'new'}, attempts=3)
        self.assertEqual(replace.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(json.loads(self.path.read_bytes()), self.old)
        pending = self.path.with_name(self.path.name + '.' + str(os.getpid()) + '.pending')
        self.assertEqual(json.loads(pending.read_bytes()), {'status': 'new'})

    def test_unrelated_permission_error_is_not_retried(self):
        with patch.object(atomic.os, 'replace', side_effect=PermissionError('permanent permission error')) as replace:
            with self.assertRaises(PermissionError):
                atomic.atomic_json_dump(self.path, {'status': 'new'})
        self.assertEqual(replace.call_count, 1)
        self.assertEqual(json.loads(self.path.read_bytes()), self.old)

    @unittest.skipUnless(os.name == 'nt', 'Real Windows file-sharing check')
    def test_real_windows_reader_lock_then_release(self):
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        # FILE_SHARE_READ permits reading, but forbids replacement until closed.
        handle = create(str(self.path), 0x80000000, 1, None, 3, 0, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        released = threading.Event()

        def unlock():
            time.sleep(0.12)
            close(handle)
            released.set()

        thread = threading.Thread(target=unlock)
        thread.start()
        try:
            used = atomic.atomic_json_dump(self.path, {'status': 'after-lock'}, attempts=8)
            self.assertGreater(used, 1)
            self.assertEqual(json.loads(self.path.read_bytes()), {'status': 'after-lock'})
        finally:
            thread.join(timeout=2)
            if not released.is_set():
                close(handle)


if __name__ == '__main__':
    unittest.main()
