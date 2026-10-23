"""Exercise the Mac login scripts with isolated HOME and fake system tools."""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parent.parent / 'launchers/macos/widget'
LABEL = 'work.markflow.gpuqueue.widget.linlishuo.autostart'
STUB = '''#!/usr/bin/python3
import json, os, pathlib, plistlib, sys
root = pathlib.Path(os.environ['AUTOSTART_TEST_ROOT'])
kind = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if kind == 'PlistBuddy':
    value = plistlib.loads(pathlib.Path(args[-1]).read_bytes())
    print(value[args[1].split(':')[-1]])
elif kind == 'plutil':
    plistlib.loads(pathlib.Path(args[-1]).read_bytes())
elif kind == 'launchctl':
    with (root/'calls').open('a') as f: f.write(json.dumps(args)+'\\n')
    registered = root/'registered'
    if args[0] == 'print':
        if args[1].count('/') == 1:
            sys.exit(1 if os.environ.get('AUTOSTART_NO_GUI') else 0)
        sys.exit(0 if registered.exists() else 1)
    if args[0] == 'bootstrap':
        if os.environ.get('AUTOSTART_FAIL_BOOTSTRAP'): sys.exit(5)
        data = plistlib.loads(pathlib.Path(args[2]).read_bytes())
        assert data['ProgramArguments'][0] == '/usr/bin/open'
        assert pathlib.Path(data['ProgramArguments'][-1]).is_dir()
        registered.write_text(args[2])
    if args[0] == 'bootout': registered.unlink()
'''


class WidgetAutostartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='widget login ')
        self.root = Path(self.temp.name)
        self.home = self.root / 'Mac 用户 & <test> "quote" \'apostrophe\''
        self.app = self.home / 'Applications/GPU 任务台小组件.app'
        (self.app / 'Contents').mkdir(parents=True)
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'work.markflow.gpuqueue.widget.linlishuo',
        }))
        self.plist = self.home / f'Library/LaunchAgents/{LABEL}.plist'
        self.plist.parent.mkdir(parents=True)
        self.other = self.plist.parent / 'another.app.plist'
        self.other.write_bytes(b'keep this unchanged')
        self.env = dict(os.environ, HOME=str(self.home), AUTOSTART_TEST_ROOT=str(self.root))
        for tool, variable in [('launchctl', 'GPUQ_LAUNCHCTL_BIN'),
                               ('plutil', 'GPUQ_PLUTIL_BIN'),
                               ('PlistBuddy', 'GPUQ_PLISTBUDDY_BIN')]:
            executable = self.root / tool
            executable.write_text(STUB)
            executable.chmod(0o700)
            self.env[variable] = str(executable)

    def tearDown(self):
        self.assertEqual(self.other.read_bytes(), b'keep this unchanged')
        self.temp.cleanup()

    def invoke(self, script):
        return subprocess.run(['/bin/bash', str(SOURCE / script)], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def test_enable_repeat_disable_and_reenable_preserve_paths_and_other_items(self):
        for _ in range(2):
            result = self.invoke('Enable-Autostart.command')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = plistlib.loads(self.plist.read_bytes())
        self.assertEqual(data['ProgramArguments'], ['/usr/bin/open', '-g', str(self.app)])
        self.assertTrue(data['RunAtLoad'])
        self.assertEqual(data['LimitLoadToSessionType'], 'Aqua')
        self.assertNotIn('KeepAlive', data)
        self.assertEqual(self.plist.stat().st_mode & 0o777, 0o600)
        for _ in range(2):
            result = self.invoke('Disable-Autostart.command')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.plist.exists())
        self.assertFalse((self.root / 'registered').exists())
        self.assertTrue(self.app.is_dir())
        self.assertEqual(self.invoke('Enable-Autostart.command').returncode, 0)
        calls = [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]
        self.assertEqual(sum(call[0] == 'bootout' for call in calls), 2)

    def test_failed_registration_does_not_report_enabled(self):
        self.env['AUTOSTART_FAIL_BOOTSTRAP'] = '1'
        result = self.invoke('Enable-Autostart.command')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('已开启开机自启动', result.stdout)
        self.assertIn('系统未成功启用', result.stdout)

    def test_not_logged_into_desktop_does_not_install_login_item(self):
        self.env['AUTOSTART_NO_GUI'] = '1'
        result = self.invoke('Enable-Autostart.command')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.plist.exists())

    def test_refuses_unrelated_app_or_replaced_login_item(self):
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'other'}))
        result = self.invoke('Enable-Autostart.command')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.plist.exists())
        unrelated = plistlib.dumps({'Label': 'other'})
        self.plist.write_bytes(unrelated)
        result = self.invoke('Disable-Autostart.command')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.plist.read_bytes(), unrelated)


if __name__ == '__main__':
    unittest.main()
