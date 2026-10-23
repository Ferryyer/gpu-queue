"""Exercise installer swaps and rollback using fake Mac tools and private HOME."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parent.parent / 'launchers/macos/widget'
STUB = '''#!/usr/bin/python3
import json, os, pathlib, plistlib, sys
root = pathlib.Path(os.environ['INSTALL_TEST_ROOT'])
kind = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with (root/'calls').open('a') as f: f.write(json.dumps([kind]+args)+'\\n')
if kind == 'osacompile':
    if os.environ.get('INSTALL_FAIL_COMPILE'): sys.exit(3)
    app = pathlib.Path(args[args.index('-o')+1])
    (app/'Contents/Resources').mkdir(parents=True)
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps({}))
elif kind == 'PlistBuddy':
    command = args[1].split(' ')
    file = pathlib.Path(args[2])
    data = plistlib.loads(file.read_bytes())
    action, key = command[0], command[1][1:]
    if action == 'Print':
        if key not in data: sys.exit(1)
        print(data[key]); sys.exit()
    if action == 'Set':
        if key not in data: sys.exit(1)
        value = command[2]
    else:
        value = command[3]
    data[key] = (value == 'true') if value in ['true','false'] else value
    file.write_bytes(plistlib.dumps(data))
elif kind == 'move':
    if os.environ.get('INSTALL_FAIL_SWAP') and '.gpuq-widget.' in str(pathlib.Path(args[0]).parent): sys.exit(9)
    os.rename(args[0],args[1])
elif kind == 'open' and os.environ.get('INSTALL_FAIL_OPEN'):
    sys.exit(4)
'''


class WidgetInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='widget install ')
        self.root = Path(self.temp.name)
        self.home = self.root / 'Mac 用户 & "quoted"'
        self.app = self.home / 'Applications/GPU 任务台小组件.app'
        (self.app/'Contents').mkdir(parents=True)
        (self.app/'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier':'work.markflow.gpuqueue.widget.linlishuo',
            'CFBundleShortVersionString':'1.0.0',
        }))
        (self.app/'old-marker').write_text('previous app')
        self.state = self.home/'Library/Application Support/GPU Queue'
        self.state.mkdir(parents=True)
        self.preferences = self.state/'ssh-config-path'
        self.preferences.write_text('/Users/me/SSH configs/config')
        self.handoff = self.state/'update-test-session'
        self.handoff.mkdir()
        self.package = self.root/'更新安装包'
        self.package.mkdir()
        shutil.copy(SOURCE/'Install.command',self.package/'安装桌面小组件.command')
        shutil.copy(SOURCE/'Autostart.command',self.package/'Autostart.command')
        for filename in ['Widget.bundle.js','Updater.bundle.js','Open-GPU-Queue.command']:
            (self.package/filename).write_text('// test asset\n')
        (self.package/'VERSION').write_text('1.1.0\n')
        self.env = dict(os.environ, HOME=str(self.home), INSTALL_TEST_ROOT=str(self.root))
        for name, variable in [('osacompile','GPUQ_OSACOMPILE_BIN'),('PlistBuddy','GPUQ_PLISTBUDDY_BIN'),
                               ('codesign','GPUQ_CODESIGN_BIN'),('open','GPUQ_OPEN_BIN'),
                               ('osascript','GPUQ_OSASCRIPT_BIN'),('move','GPUQ_MOVE_BIN'),
                               ('launchctl','GPUQ_LAUNCHCTL_BIN'),('plutil','GPUQ_PLUTIL_BIN')]:
            executable = self.root/name
            executable.write_text(STUB)
            executable.chmod(0o700)
            self.env[variable] = str(executable)
        self.children = []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None: child.terminate()
            child.communicate(timeout=10)
        self.assertEqual(self.preferences.read_text(),'/Users/me/SSH configs/config')
        self.temp.cleanup()

    def start(self, update=True):
        args = ['/bin/bash',str(self.package/'安装桌面小组件.command')]
        if update: args += ['--update',str(self.handoff)]
        child = subprocess.Popen(args,env=self.env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        self.children.append(child)
        return child

    def prepared(self, child):
        until = time.monotonic()+10
        while time.monotonic()<until:
            if (self.handoff/'ready').exists(): return
            if child.poll() is not None: self.fail(child.communicate()[0])
            time.sleep(.05)
        self.fail('Installer never reached the handoff')

    def test_waits_for_handoff_then_updates_and_preserves_disabled_autostart(self):
        child = self.start()
        self.prepared(child)
        self.assertTrue((self.app/'old-marker').exists())
        self.assertIsNone(child.poll())
        (self.handoff/'continue').write_text('install')
        out = child.communicate(timeout=10)[0]
        self.assertEqual(child.returncode,0,out)
        info = plistlib.loads((self.app/'Contents/Info.plist').read_bytes())
        self.assertEqual(info['CFBundleShortVersionString'],'1.1.0')
        self.assertTrue((self.app/'Contents/Helpers/GPU 任务台更新器.app/Contents/Info.plist').exists())
        backups = list(self.app.parent.glob('*.previous-*.app'))
        self.assertEqual(len(backups),1)
        self.assertTrue((backups[0]/'old-marker').exists())
        self.assertNotIn('launchctl',(self.root/'calls').read_text())

    def test_enabled_login_item_is_preserved_exactly_during_update(self):
        item = self.home/'Library/LaunchAgents/work.markflow.gpuqueue.widget.linlishuo.autostart.plist'
        item.parent.mkdir(parents=True)
        item.write_bytes(b'personal login preference')
        child = self.start(); self.prepared(child)
        (self.handoff/'continue').write_text('install')
        out = child.communicate(timeout=10)[0]
        self.assertEqual(child.returncode,0,out)
        self.assertEqual(item.read_bytes(),b'personal login preference')

    def test_compile_failure_keeps_old_app_and_does_not_signal_readiness(self):
        self.env['INSTALL_FAIL_COMPILE'] = '1'
        child = self.start(); out = child.communicate(timeout=10)[0]
        self.assertNotEqual(child.returncode,0,out)
        self.assertTrue((self.app/'old-marker').exists())
        self.assertFalse((self.handoff/'ready').exists())
        self.assertNotIn('open',(self.root/'calls').read_text())

    def test_failed_swap_and_failed_launch_restore_old_app(self):
        for failure in ['INSTALL_FAIL_SWAP','INSTALL_FAIL_OPEN']:
            with self.subTest(failure=failure):
                self.env.pop('INSTALL_FAIL_SWAP',None)
                self.env[failure] = '1'
                for flag in ['ready','continue']:
                    (self.handoff/flag).unlink(missing_ok=True)
                child = self.start(); self.prepared(child)
                (self.handoff/'continue').write_text('install')
                out = child.communicate(timeout=10)[0]
                self.assertNotEqual(child.returncode,0,out)
                self.assertTrue((self.app/'old-marker').exists())

    def test_cancel_while_waiting_keeps_old_app(self):
        child = self.start(); self.prepared(child)
        child.terminate(); child.communicate(timeout=10)
        self.assertTrue((self.app/'old-marker').exists())
        self.assertEqual(list(self.app.parent.glob('.gpuq-widget.*')),[])

    def test_manual_install_upgrades_old_app_and_enables_login(self):
        child = self.start(update=False); out = child.communicate(timeout=10)[0]
        self.assertEqual(child.returncode,0,out)
        calls = [json.loads(line) for line in (self.root/'calls').read_text().splitlines()]
        self.assertTrue(any(call[0]=='osascript' for call in calls))
        self.assertTrue(any(call[0]=='launchctl' and call[1]=='bootstrap' for call in calls))


if __name__ == '__main__': unittest.main()
