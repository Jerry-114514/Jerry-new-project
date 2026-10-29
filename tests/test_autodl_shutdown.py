import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import additional_gpu_time_guard as shutdown


class ShutdownTests(unittest.TestCase):
    def setUp(self):
        p=patch.object(shutdown.sys,'platform','linux');p.start();self.addCleanup(p.stop)

    def test_non_linux_never_executes_a_local_shutdown(self):
        with patch.object(shutdown.sys,'platform','win32'),patch.object(shutdown.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'Linux-only'):shutdown.request_shutdown()
            run.assert_not_called()

    def test_direct_success_is_not_provider_confirmation(self):
        with patch.object(shutdown.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run:
            result=shutdown.request_shutdown()
        self.assertEqual(result,{'method':'direct','returncode':0,'provider_stop_verified':False})
        self.assertEqual(run.call_args.args[0],['/usr/bin/shutdown'])

    def test_enoexec_requires_syntax_validation_before_bash(self):
        effects=[OSError(errno.ENOEXEC,'Exec format'),subprocess.CompletedProcess([],0),subprocess.CompletedProcess([],0)]
        with patch.object(shutdown.subprocess,'run',side_effect=effects) as run,patch.object(Path,'read_bytes',return_value=b'echo stop\n'),patch.object(Path,'is_file',return_value=True):
            result=shutdown.request_shutdown()
        self.assertEqual(result['method'],'validated_bash_after_enoexec')
        self.assertEqual([c.args[0] for c in run.call_args_list],
                         [['/usr/bin/shutdown'],['/bin/bash','-n','/usr/bin/shutdown'],['/bin/bash','/usr/bin/shutdown']])

    def test_missing_command_permission_error_and_timeout_are_not_reinterpreted(self):
        for error in (FileNotFoundError(errno.ENOENT,'Missing'),PermissionError(errno.EACCES,'Denied'),subprocess.TimeoutExpired([],30)):
            with self.subTest(error=type(error).__name__),patch.object(shutdown.subprocess,'run',side_effect=error) as run:
                with self.assertRaises(type(error)):shutdown.request_shutdown()
                self.assertEqual(run.call_count,1)

    def test_binary_and_invalid_shell_are_rejected(self):
        with patch.object(shutdown.subprocess,'run',side_effect=OSError(errno.ENOEXEC,'Format')) as run,patch.object(Path,'read_bytes',return_value=b'\x00binary'),patch.object(Path,'is_file',return_value=True):
            with self.assertRaisesRegex(ValueError,'text'):shutdown.request_shutdown()
            self.assertEqual(run.call_count,1)
        effects=[OSError(errno.ENOEXEC,'Format'),subprocess.CompletedProcess([],2)]
        with patch.object(shutdown.subprocess,'run',side_effect=effects) as run,patch.object(Path,'read_bytes',return_value=b'if (\n'),patch.object(Path,'is_file',return_value=True):
            with self.assertRaisesRegex(ValueError,'syntax'):shutdown.request_shutdown()
            self.assertEqual(run.call_count,2)

    def test_nonzero_provider_result_remains_nonzero(self):
        with patch.object(shutdown.subprocess,'run',return_value=subprocess.CompletedProcess([],7)):
            result=shutdown.request_shutdown()
        self.assertEqual(result['returncode'],7);self.assertFalse(result['provider_stop_verified'])


@unittest.skipUnless(sys.platform=='linux','Real ENOEXEC behavior is Linux-specific')
class NativeShutdownTests(unittest.TestCase):
    def test_actual_script_without_shebang_uses_validated_bash(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fake-official';path.write_text('exit 0\n');path.chmod(0o700)
            result=shutdown._invoke_shutdown(path)
            self.assertEqual(result['method'],'validated_bash_after_enoexec')
            self.assertEqual(result['returncode'],0);self.assertFalse(result['provider_stop_verified'])


if __name__=='__main__':unittest.main()
