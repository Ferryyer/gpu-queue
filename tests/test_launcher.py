"""Exercise launch/open/reuse/failure without any real SSH connection."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from gpuqueue.core import HOME

LAUNCHER = Path(__file__).resolve().parent.parent/'launchers/macos/Open-GPU-Queue.command'
STUB = '''#!/usr/bin/python3
import json,os,pathlib,signal,sys,time,urllib.parse
root=pathlib.Path(os.environ['LAUNCHER_TEST_ROOT']);kind=pathlib.Path(sys.argv[0]).name
if kind=='ssh':
 if '-G' in sys.argv:print('hostname cpu.test.invalid');sys.exit(0)
 port=sys.argv[sys.argv.index('-L')+1].split(':')[1]
 with (root/'ssh-calls').open('a') as f:f.write(port+'\\n')
 mode=os.environ.get('LAUNCHER_TEST_MODE','')
 if mode=='failure':print('Permission denied (publickey).',file=sys.stderr);sys.exit(255)
 if mode=='conflict' and port=='8790':print('bind: Address already in use',file=sys.stderr);sys.exit(255)
 ready=root/('ready-'+port);ready.write_text(str(os.getpid()))
 signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
 try:
  while True:time.sleep(.1)
 finally:ready.unlink(missing_ok=True)
elif kind=='curl':
 port=str(urllib.parse.urlparse(sys.argv[-1]).port)
 if (root/('ready-'+port)).exists():print('{"owner":"linlishuo","service":"gpuq","uid":21005}')
 else:sys.exit(22)
elif kind=='open':
 with (root/'opened').open('a') as f:f.write(sys.argv[-1]+'\\n')
'''

class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='mac launcher ',dir=HOME/'scratch')
        self.root=Path(self.temp.name)
        for name in ['ssh','curl','open']:
            p=self.root/name;p.write_text(STUB);p.chmod(0o700)
        config=self.root/'member config';config.write_text('Host markflow-cpu\n HostName cpu.test.invalid\n')
        self.env=dict(os.environ,LAUNCHER_TEST_ROOT=str(self.root),GPUQ_SSH_BIN=str(self.root/'ssh'),GPUQ_CURL_BIN=str(self.root/'curl'),GPUQ_OPEN_BIN=str(self.root/'open'),GPUQ_SSH_CONFIG=str(config),GPUQ_LAUNCHER_STATE_DIR=str(self.root/'state'))
        self.processes=[]
    def tearDown(self):
        for p in self.processes:
            if p.poll() is None:p.terminate()
            p.communicate(timeout=5)
        self.temp.cleanup()
    def start(self):
        p=subprocess.Popen(['/bin/bash',str(LAUNCHER)],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        self.processes.append(p);return p
    def await_browser(self,p):
        for _ in range(150):
            if (self.root/'opened').exists():return
            if p.poll() is not None:self.fail(p.communicate()[0])
            time.sleep(.1)
        self.fail('Browser was not opened')
    def test_first_launch_connects_and_second_click_reuses_tunnel(self):
        first=self.start();self.await_browser(first)
        second=self.start();out=second.communicate(timeout=10)[0];self.assertEqual(second.returncode,0,out)
        self.assertEqual((self.root/'ssh-calls').read_text().splitlines(),['8790'])
        self.assertEqual((self.root/'opened').read_text().splitlines(),['http://127.0.0.1:8790/']*2)
        first.terminate();first.communicate(timeout=5)
        self.assertFalse((self.root/'ready-8790').exists())
    def test_busy_port_uses_another_local_port_without_killing_other_apps(self):
        self.env['LAUNCHER_TEST_MODE']='conflict'
        p=self.start();self.await_browser(p)
        self.assertEqual((self.root/'opened').read_text().strip(),'http://127.0.0.1:8791/')
        self.assertEqual((self.root/'ssh-calls').read_text().splitlines(),['8790','8791'])
    def test_authentication_failure_does_not_open_a_dead_page(self):
        self.env['LAUNCHER_TEST_MODE']='failure'
        p=self.start();out=p.communicate(timeout=10)[0]
        self.assertEqual(p.returncode,1,out)
        self.assertFalse((self.root/'opened').exists())
        self.assertIn('Permission denied',out)
        self.assertFalse((self.root/'state/connecting').exists())

if __name__=='__main__':unittest.main()
