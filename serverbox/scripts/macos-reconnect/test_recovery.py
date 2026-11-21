"""Exercise the actual native helper with a loopback server and fake launchctl."""
import json
import importlib.util
import os
from pathlib import Path
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest


class Banner(socketserver.BaseRequestHandler):
    def handle(self):
        if self.server.healthy:
            self.request.sendall(b'SSH-2.')
            self.request.sendall(b'0-TestServer\r\n')
        else:
            # Accepting TCP is insufficient: simulate a wedged forward.
            time.sleep(0.6)


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.build.name)/'recovery'
        subprocess.run(['swiftc', '-swift-version', '5',
                        str(Path(__file__).with_name('TunnelRecovery.swift')),
                        '-o', str(cls.binary)], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.log = self.root/'launchctl.jsonl'
        self.fake = self.root/'launchctl'
        self.fake.write_text('#!'+sys.executable+'\nimport json,sys,time\n'
                             f'with open({str(self.log)!r}, "a") as out: '
                             'out.write(json.dumps(dict(at=time.monotonic(), args=sys.argv[1:]))+"\\n")\n')
        self.fake.chmod(0o700)
        self.server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Banner)
        self.server.daemon_threads = True
        self.server.healthy = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.status = self.root/'status.json'
        self.config = self.root/'config.json'
        self.config.write_text(json.dumps(dict(port=self.server.server_address[1], label='isolated-test',
                                launchctl=str(self.fake), statusFile=str(self.status), interval=0.3, timeout=0.2)))
        self.config.chmod(0o600)
        self.process = None

    def tearDown(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def start(self):
        self.process = subprocess.Popen([str(self.binary), '--config', str(self.config)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait_for(self, predicate, timeout=8):
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            if predicate():
                return
            if self.process and self.process.poll() is not None:
                self.fail('Native helper exited unexpectedly')
            time.sleep(0.05)
        self.fail('Timed out waiting for recovery state')

    def state(self):
        try:
            return json.loads(self.status.read_text())['state']
        except (FileNotFoundError, ValueError):
            return None

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_healthy_banner_is_not_restarted_and_status_is_private(self):
        self.start()
        self.wait_for(lambda: self.state() == 'connected')
        time.sleep(0.7)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.status.stat().st_mode & 0o077, 0)

    def test_wedged_forward_restarts_only_named_service_with_backoff(self):
        self.server.healthy = False
        self.start()
        self.wait_for(lambda: len(self.calls()) == 1)
        time.sleep(1.3)
        calls = self.calls()
        self.assertEqual(len(calls), 1, 'A failed tunnel must not cause a restart storm')
        self.assertEqual(calls[0]['args'], ['kickstart', '-k', f'gui/{os.getuid()}/isolated-test'])
        self.server.healthy = True
        self.wait_for(lambda: self.state() == 'connected')

    def test_sleep_suppresses_restarts_and_wake_rechecks_and_recovers(self):
        self.start()
        self.wait_for(lambda: self.state() == 'connected')
        self.process.send_signal(signal.SIGUSR2)
        self.wait_for(lambda: self.state() == 'sleeping')
        self.server.healthy = False
        time.sleep(1.2)
        self.assertEqual(self.calls(), [])
        self.process.send_signal(signal.SIGUSR1)
        self.wait_for(lambda: len(self.calls()) == 1)
        self.server.healthy = True
        self.wait_for(lambda: self.state() == 'connected')

    def test_refuses_shared_configuration(self):
        self.config.chmod(0o644)
        result = subprocess.run([str(self.binary), '--config', str(self.config)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())

    def test_missing_listener_is_allowed_to_finish_ssh_authentication(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            unused = probe.getsockname()[1]
        config = json.loads(self.config.read_text())
        config['port'] = unused
        self.config.write_text(json.dumps(config))
        self.start()
        self.wait_for(lambda: self.state() == 'waiting_tunnel')
        time.sleep(1.0)
        self.assertEqual(self.calls(), [])
        self.server.shutdown()
        self.server.server_close()
        self.server = socketserver.ThreadingTCPServer(('127.0.0.1', unused), Banner)
        self.server.daemon_threads = True
        self.server.healthy = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.wait_for(lambda: self.state() == 'connected')
        self.assertEqual(self.calls(), [])

    def test_installation_keeps_forward_private_and_both_hops_bounded(self):
        spec = importlib.util.spec_from_file_location('recovery_install', Path(__file__).with_name('install.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        config = module.tunnel_agent(self.root, dict(Label=module.TUNNEL))
        argv = config['ProgramArguments']
        self.assertIn('127.0.0.1:22224:127.0.0.1:22223', argv)
        self.assertIn('BatchMode=yes', argv)
        self.assertIn('ServerAliveCountMax=2', argv)
        proxy = next(arg for arg in argv if arg.startswith('ProxyCommand='))
        self.assertIn('ConnectTimeout=20', proxy)
        self.assertIn('ConnectTimeout=30', argv)
        self.assertIn('ServerAliveCountMax=2', proxy)
        self.assertNotIn('StrictHostKeyChecking=no', ' '.join(argv))
        self.assertNotIn('UserKnownHostsFile=/dev/null', ' '.join(argv))
        self.assertEqual(argv[-1], 'markflow-cpu')


if __name__ == '__main__':
    unittest.main()
