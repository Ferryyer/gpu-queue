import importlib.util
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'serverbox/crates/sbm_parser/src/scripts/result_preview'
spec = importlib.util.spec_from_file_location('preview_ensure', SOURCE / 'ensure.py')
ensure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ensure)


class ResultPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='iq-preview-', dir='/tmp')
        self.home = Path(self.temp.name) / 'home'
        self.home.mkdir(mode=0o700)
        self.directory = Path(self.temp.name) / 'sock'
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (ProcessLookupError, ChildProcessError):
                pass
        self.temp.cleanup()

    def start(self):
        process = ensure.bootstrap(self.home, self.directory, (SOURCE / 'fileshare.py').read_bytes())
        if process:
            self.processes.append(process)
        return process

    def request(self, path):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(3)
        client.connect(str(self.directory / 'web.sock'))
        with client:
            client.sendall(f'GET {path} HTTP/1.0\r\nHost: 127.0.0.1:8780\r\n\r\n'.encode())
            data = bytearray()
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    return bytes(data)
                data.extend(chunk)

    def test_new_account_starts_once_and_serves_registered_pages_and_assets(self):
        self.assertIsInstance(self.start(), subprocess.Popen)
        self.assertIsNone(self.start())
        self.assertEqual((self.home / '.inspire-preview.sock').resolve(), (self.directory / 'web.sock').resolve())
        self.assertEqual((self.directory.stat().st_mode & 0o777), 0o700)
        self.assertEqual(((self.directory / 'web.sock').stat().st_mode & 0o777), 0o600)
        project = self.home / 'project'
        project.mkdir()
        (project / 'index.html').write_text('<h1>result</h1><script src="app.js"></script>')
        (project / 'second.html').write_text('<h1>second result</h1>')
        (project / 'app.js').write_text('window.preview = true;')
        subprocess.run([str(self.home / '.local/bin/fshare'), str(project)],
                       env={**os.environ, 'HOME': str(self.home)}, check=True, capture_output=True)
        registry = json.loads((self.home / '.local/state/fileshare/links.json').read_text())
        token = next(iter(registry))
        for name in ('index.html', 'second.html'):
            self.assertIn(b'200 OK', self.request(f'/f/{token}/project/{name}'))
        relay = subprocess.run([sys.executable, '-I', str(SOURCE / 'relay.py'), str(self.directory / 'web.sock')],
            input=f'GET /f/{token}/project/index.html HTTP/1.0\r\nHost: 127.0.0.1:8780\r\n\r\n'.encode(),
            capture_output=True, timeout=5, check=True)
        self.assertIn(b'<h1>result</h1>', relay.stdout)
        self.assertIn(b'text/javascript', self.request(f'/f/{token}/project/app.js'))
        (project / '.env').write_text('private')
        self.assertIn(b'403 Forbidden', self.request(f'/f/{token}/project/.env'))
        (project / 'escape').symlink_to('/etc/passwd')
        self.assertIn(b'403 Forbidden', self.request(f'/f/{token}/project/escape'))

    def test_existing_service_and_registration_are_preserved(self):
        self.start()
        registry = self.home / '.local/state/fileshare/links.json'
        registry.parent.mkdir(parents=True, mode=0o700)
        old_result = self.home / 'old.html'
        old_result.write_text('<h1>old result</h1>')
        registry.write_text(json.dumps({'old-token': {'path': str(old_result.resolve()),
            'name': 'old.html', 'kind': 'file', 'created': 1}}))
        before = registry.stat().st_mtime_ns
        launcher = self.home / '.local/bin/fshare'
        launcher.write_text('# existing user command\n')
        self.assertIsNone(self.start())
        self.assertEqual(launcher.read_text(), '# existing user command\n')
        self.assertEqual(registry.stat().st_mtime_ns, before)
        self.assertIn(b'old result', self.request('/f/old-token/old.html'))

    def test_concurrent_initialization_starts_one_service(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            processes = list(pool.map(lambda _: self.start(), range(2)))
        self.assertEqual(sum(p is not None for p in processes), 1)

    def test_existing_tcp_8780_is_not_changed(self):
        listener = socket.socket()
        try:
            try:
                listener.bind(('127.0.0.1', 8780))
            except OSError:
                self.skipTest('8780 is already in use by this test host')
            listener.listen()
            self.start()
            self.assertEqual(listener.getsockname()[1], 8780)
            self.assertIn(b'200 OK', self.request('/'))
        finally:
            listener.close()

    def test_stale_owned_socket_is_recovered(self):
        self.directory.mkdir(mode=0o700)
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(self.directory / 'web.sock'))
        os.chmod(self.directory / 'web.sock', 0o600)
        stale.close()
        self.start()
        self.assertIn(b'200 OK', self.request('/'))

    def test_conflicting_alias_is_not_overwritten(self):
        alias = self.home / '.inspire-preview.sock'
        alias.write_text('keep')
        with self.assertRaisesRegex(RuntimeError, '已有文件'):
            self.start()
        self.assertEqual(alias.read_text(), 'keep')

    def test_non_private_or_symlink_socket_directory_is_rejected(self):
        self.directory.mkdir(mode=0o755)
        with self.assertRaises(RuntimeError):
            self.start()
        self.directory.rmdir()
        self.directory.symlink_to(self.home, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.start()

    def test_asset_matches_reviewable_sources(self):
        subprocess.run([sys.executable, str(ROOT / 'scripts/build_result_preview_asset.py'), '--check'], check=True)


if __name__ == '__main__':
    unittest.main()
