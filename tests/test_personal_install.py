import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/install_personal_service.py'
SPEC = importlib.util.spec_from_file_location('personal_install', SCRIPT)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class PersonalInstallTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = Path(self.folder.name).resolve()
        self.source = self.home/'code/release with spaces'
        for name in ['gpuqueue/cli.py', 'gpuqueue/web.py', 'web/index.html']:
            path = self.source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture')
        self.uid = os.getuid()
        self.tools = patch.object(installer, 'tool_path', side_effect=lambda name, home: '/usr/local/bin/'+name)
        self.tools.start()
        self.addCleanup(self.tools.stop)

    def plan(self):
        return installer.plan_install(self.source, self.home, 'employee', self.uid)

    def test_dry_run_has_no_writes_and_disabled_frontend_services_only(self):
        files, changes, tools = self.plan()
        self.assertEqual(len(changes), 4)
        self.assertFalse((self.home/'.config').exists())
        services = [json.loads(content) for path, content, _ in files if path.parent.name == 'services']
        self.assertEqual([s['argv'][1] for s in services], ['serve', 'web'])
        self.assertTrue(all(s['enabled'] is False for s in services))
        self.assertTrue(all(s['env'] == {} for s in services))
        self.assertEqual(tools['mf-gpu'], '/usr/local/bin/mf-gpu')
        config = json.loads(files[0][1])
        self.assertEqual(config['username'], 'employee')
        self.assertEqual(config['home'], str(self.home))
        self.assertNotIn('linlishuo', files[1][1].replace(str(self.home), '$MEMBER_HOME'))
        self.assertIn("'" + str(self.source) + "'", files[1][1])

    def test_apply_is_private_and_idempotent(self):
        files, changes, _ = self.plan()
        installer.apply_install(changes, self.home, self.uid)
        before = {path: path.stat().st_mtime_ns for path, _, _ in files}
        self.assertEqual(self.plan()[1], [])
        for path, _, mode in files:
            self.assertEqual(path.stat().st_mode & 0o777, mode)
            self.assertEqual(path.stat().st_mtime_ns, before[path])

    def test_conflict_does_not_create_other_files_or_disable_service(self):
        path = self.home/'.config/markflow/services/gpuq.json'
        path.parent.mkdir(parents=True)
        content = '{"enabled": true, "argv": ["existing"]}'
        path.write_text(content)
        path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, '已有不同配置'):
            self.plan()
        self.assertEqual(path.read_text(), content)
        self.assertFalse((self.home/'.config/gpuq/connection.json').exists())

    def test_rejects_symlink_without_touching_target(self):
        other = self.home/'other'
        other.mkdir()
        (self.home/'.config').symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '符号链接'):
            self.plan()
        self.assertEqual(list(other.iterdir()), [])

    def test_rejects_insecure_existing_configuration(self):
        path = self.home/'.config/gpuq/connection.json'
        path.parent.mkdir(parents=True)
        path.write_text('{}')
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, '权限不同'):
            self.plan()
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_cross_home_source_rejected(self):
        with self.assertRaisesRegex(ValueError, '本人 HOME'):
            installer.plan_install(Path('/opt/shared/source'), self.home, 'employee', self.uid)

    def test_missing_tool_does_not_create_files(self):
        with patch.object(installer, 'tool_path', side_effect=ValueError('未找到 mf-gpu')):
            with self.assertRaisesRegex(ValueError, 'mf-gpu'):
                self.plan()
        self.assertFalse((self.home/'.config').exists())

    def test_apply_refuses_racing_file(self):
        _, changes, _ = self.plan()
        path = changes[0][0]
        path.parent.mkdir(parents=True)
        path.write_text('preserve')
        path.chmod(0o600)
        with self.assertRaises(FileExistsError):
            installer.apply_install(changes, self.home, self.uid)
        self.assertEqual(path.read_text(), 'preserve')

    def test_rejects_sudo_and_nonlinux(self):
        with patch.object(installer.platform, 'system', return_value='Linux'), patch.object(installer.sys, 'version_info', (3, 10)), patch.object(installer.os, 'getuid', return_value=0):
            with self.assertRaisesRegex(ValueError, 'sudo'):
                installer.identity()
        with patch.object(installer.platform, 'system', return_value='Darwin'):
            with self.assertRaisesRegex(ValueError, 'Linux'):
                installer.identity()

    def test_old_python_and_home_mismatch_are_rejected(self):
        with patch.object(installer.platform, 'system', return_value='Linux'), patch.object(installer.sys, 'version_info', (3, 9)):
            with self.assertRaisesRegex(ValueError, 'Python 3.10'):
                installer.identity()
        with patch.object(installer.platform, 'system', return_value='Linux'), patch.object(installer.sys, 'version_info', (3, 10)), patch.object(installer.os, 'getuid', return_value=21099), patch.object(installer.os, 'geteuid', return_value=21099), patch.object(installer.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir=str(self.home), pw_name='employee')):
            with self.assertRaisesRegex(ValueError, 'HOME'):
                installer.identity()

    def test_discovers_existing_user_tool_without_execution(self):
        self.tools.stop()
        executable = self.home/'.local/bin/lark-cli'
        executable.parent.mkdir(parents=True)
        executable.write_text('#!/bin/sh\nexit 99\n')
        executable.chmod(0o700)
        with patch.object(installer.shutil, 'which', return_value=None):
            self.assertEqual(installer.tool_path('lark-cli', self.home), str(executable))


if __name__ == '__main__':
    unittest.main()
