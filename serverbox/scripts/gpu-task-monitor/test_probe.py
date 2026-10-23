import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('patch_probe', Path(__file__).with_name('patch_probe.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class ProbeTests(unittest.TestCase):
    def test_source_command_matches_deployed_probe(self):
        root = Path(__file__).resolve().parents[2]
        lines = (root / 'crates/sbm_parser/src/commands.rs').read_text().splitlines()
        line = next(line for line in lines if 'cmd:' in line and 'serverbox-gpu-status' in line)
        self.assertEqual(json.loads(line.split('cmd: ', 1)[1].rstrip(',')), p.NEW)

    def test_native_gpu_takes_priority_and_bridge_is_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            bin = home / 'bin'
            helper = home / '.local/bin/serverbox-gpu-status'
            bin.mkdir()
            helper.parent.mkdir(parents=True)
            helper.write_text('#!/bin/sh\nprintf bridge')
            helper.chmod(0o700)
            env = dict(os.environ, HOME=folder, PATH=str(bin))
            result = subprocess.check_output(['/bin/sh', '-c', p.NEW], env=env, text=True)
            self.assertEqual(result, 'bridge')
            native = bin / 'nvidia-smi'
            native.write_text('#!/bin/sh\nprintf native')
            native.chmod(0o700)
            result = subprocess.check_output(['/bin/sh', '-c', p.NEW], env=env, text=True)
            self.assertEqual(result, 'native')

    def test_script_patch_is_atomic_idempotent_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'srvboxm_v87.sh'
            original = '#!/bin/sh\n' + p.OLD + '\n'
            path.write_text(original)
            path.chmod(0o700)
            self.assertTrue(p.patch_script(path))
            self.assertFalse(p.patch_script(path))
            self.assertEqual(path.read_text(), '#!/bin/sh\n' + p.NEW + '\n')
            self.assertEqual(path.with_suffix('.sh.before-gpu-monitor').read_text(), original)
            link = Path(folder) / 'link.sh'
            link.symlink_to(path)
            self.assertFalse(p.patch_script(link))


if __name__ == '__main__':
    unittest.main()
