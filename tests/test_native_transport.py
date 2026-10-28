"""Exercise the exact embedded native bridge against an isolated Unix HTTP service."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from gpuqueue.core import HOME, Store, canonical
from gpuqueue.control import Control
from gpuqueue.web import Server, Handler

class NativeTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HOME/'scratch')
        self.root = Path(self.temp.name)
        self.store = Store(self.root/'store')
        self.control = Control(self.store)
        self.id = 'GQ-0000000000000001'
        self.digest = 'a'*64
        with self.store.connect() as db:
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)', (self.id, self.digest, '{}', canonical({'id':self.id,'name':'isolated CPU fixture','state':'ready','events':[]}), '{}'))
        source = (Path(__file__).resolve().parent.parent/'serverbox/lib/core/gpu_queue/protocol.dart').read_text()
        self.script = source.split("static const script = r'''",1)[1].split("'''",1)[0]
        self.socket = self.root/'web.sock'
        self.script = self.script.replace("'/tmp/gpuq-%d/web.sock'%os.getuid()", repr(str(self.socket)))
        self.server = Server(str(self.socket),Handler)
        self.server.control = self.control
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
        self.temp.cleanup()
    def request(self,path,body=None):
        request=base64.b64encode(json.dumps(dict(path=path,body=body)).encode()).decode()
        result=subprocess.run([sys.executable,'-c',self.script,request],capture_output=True,text=True,timeout=20,check=True)
        return json.loads(result.stdout)
    def test_reads_and_reconnect_do_not_approve(self):
        for _ in range(3):
            state=self.request('/api/state')
            self.assertEqual(state['status'],200)
            self.assertIsNone(state['body']['tasks'][0]['approved_at'])
    def test_only_explicit_version_bound_start_can_approve(self):
        bad=self.request('/api/tasks/'+self.id+'/start',{'digest':"'; touch /tmp/native-injection; $()"})
        self.assertEqual(bad['status'],409)
        self.assertIsNone(self.control.state()['tasks'][0]['approved_at'])
        good=self.request('/api/tasks/'+self.id+'/start',{'digest':self.digest})
        self.assertEqual(good['status'],200)
        self.assertIsNotNone(good['body']['tasks'][0]['approved_at'])
        self.assertEqual(good,self.request('/api/tasks/'+self.id+'/start',{'digest':self.digest}))
    def test_stop_and_stale_reorder_use_existing_authority(self):
        self.request('/api/tasks/'+self.id+'/start',{'digest':self.digest})
        self.assertEqual(self.request('/api/queue/reorder',{'ids':[self.id],'revision':-1})['status'],409)
        stopped=self.request('/api/tasks/'+self.id+'/stop',{'digest':self.digest})
        self.assertEqual(stopped['status'],200)
        self.assertEqual(stopped['body']['tasks'][0]['state'],'cancelled')
    def test_delete_and_cleanup_reach_the_private_service(self):
        state = self.request('/api/state')['body']
        self.assertTrue(state['capabilities']['task_delete'])
        self.assertEqual(self.request('/api/tasks/cleanup', {'ids':[self.id], 'revision':state['revision']})['status'],409)
        task = self.store.get(self.id)
        task['public']['state'] = 'completed'
        self.store.save(task)
        result = self.request('/api/tasks/cleanup', {'ids':[self.id], 'revision':state['revision']})
        self.assertEqual(result['status'],200)
        self.assertEqual(result['body']['tasks'],[])
        self.assertEqual(self.request('/api/tasks/'+self.id+'/delete',{'digest':'bad'})['status'],409)
        self.assertEqual(self.request('/api/tasks/'+self.id+'/delete',{'digest':self.digest})['body']['tasks'],[])
        self.assertIsNotNone(self.store.get(self.id))

    def test_unavailable_service_is_not_successful_empty_state(self):
        self.script=self.script.replace(repr(str(self.socket)),repr(str(self.root/'x')))
        result=self.request('/api/state')
        self.assertEqual(result['status'],503)
        self.assertIn('FileNotFoundError',result['body']['error'])
