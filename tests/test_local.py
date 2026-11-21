import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock
from gpuqueue.core import HOME, Store, canonical
from gpuqueue.control import Control, ControlError, QueueChanged
from gpuqueue.service import Service

class LocalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HOME/'scratch')
        self.root = Path(self.temp.name)
        self.store = Store(self.root/'state')
        self.control = Control(self.store)
        self.ids = ['GQ-'+str(i).zfill(16) for i in range(1,4)]
        for i, task_id in enumerate(self.ids):
            public = {'id':task_id,'name':'test','state':'ready','created_at':str(i),'events':[]}
            internal = {'approved_at':None,'position':0,'dispatch':None}
            with self.store.connect() as db:
                db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)', (task_id,str(i)*64,'{}',canonical(public),canonical(internal)))
    def tearDown(self):
        self.temp.cleanup()
    def test_start_is_version_bound_persistent_and_idempotent(self):
        with self.assertRaises(ControlError): self.control.start(self.ids[0], 'bad')
        self.assertIsNone(self.control.state()['tasks'][0]['approved_at'])
        first = self.control.start(self.ids[0], '0'*64)
        again = Control(self.store).start(self.ids[0], '0'*64)
        self.assertEqual(first, again)
        self.assertEqual(next(t for t in first['tasks'] if t['id']==self.ids[0])['state'], 'queued')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM queue_audit').fetchone()[0], 1)
    def test_reorder_and_dispatch_are_atomic_and_reject_stale_revisions(self):
        self.control.start(self.ids[0], '0'*64)
        state = self.control.start(self.ids[1], '1'*64)
        reordered = self.control.reorder([self.ids[1],self.ids[0]],state['revision'])
        with self.assertRaises(QueueChanged): self.control.claim(self.ids[0], '0'*64, state['revision'])
        with self.assertRaises(QueueChanged): self.control.claim(self.ids[0], '0'*64, reordered['revision'])
        self.control.claim(self.ids[1], '1'*64, reordered['revision'])
        with self.assertRaises(QueueChanged): self.control.reorder([self.ids[1],self.ids[0]], reordered['revision'])
        with self.assertRaises(QueueChanged): self.control.claim(self.ids[2], '2'*64, self.control.state()['revision'])
    def test_migration_preserves_authorizations_positions_and_claims_once(self):
        snapshot = {'revision':19,'tasks':[{'id':self.ids[1],'digest':'1'*64,'position':3,'approved_at':'original approval','claimed_at':'original claim'},{'id':self.ids[0],'digest':'0'*64,'position':4,'approved_at':None,'claimed_at':None}]}
        state = self.control.import_snapshot(snapshot)
        migrated = next(t for t in state['tasks'] if t['id']==self.ids[1])
        self.assertEqual(migrated['approved_at'],'original approval')
        self.assertEqual(migrated['claimed_at'],'original claim')
        self.assertEqual(migrated['state'],'dispatching')
        self.assertEqual(migrated['position'],3)
        self.assertEqual(state['revision'],19)
        with self.assertRaises(ControlError): self.control.import_snapshot(snapshot)
    def test_migration_rolls_back_on_missing_or_changed_snapshot(self):
        snapshot={'revision':5,'tasks':[{'id':self.ids[0],'digest':'wrong','position':0}]}
        with self.assertRaises(ControlError): self.control.import_snapshot(snapshot)
        self.assertEqual(self.control.state()['revision'],0)
    def test_local_scheduler_waits_for_browser_authorization(self):
        platform=Mock();platform.resources={}
        service=Service({},self.store,platform)
        service.tick()
        platform.request.assert_not_called();platform.select.assert_not_called();platform.submit_job.assert_not_called()
        self.control.start(self.ids[0],'0'*64)
        service.sync()
        self.assertTrue(self.store.get(self.ids[0])['internal']['approved_at'])
        self.assertIsNone(self.store.get(self.ids[1])['internal']['approved_at'])
    def test_unix_http_boundary_has_no_worker_or_submit_api(self):
        sock=self.root/'web.sock'
        # Dedicated process avoids thread dependencies; no scheduler or GPU adapter.
        child=subprocess.Popen(['/usr/bin/python3','-c','from gpuqueue.web import serve; from gpuqueue.core import Store; import sys; serve(Store(sys.argv[1]),sys.argv[2])',str(self.store.root),str(sock)],stdout=subprocess.DEVNULL)
        class Connection(http.client.HTTPConnection):
            def connect(connection):
                connection.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
                connection.sock.settimeout(5);connection.sock.connect(str(sock))
        def request(method,path,data=None,headers=None,host='127.0.0.1:8790'):
            conn=Connection(host)
            body=json.dumps(data) if data is not None else None
            conn.request(method,path,body,headers or {})
            response=conn.getresponse();result=response.read();status=response.status;conn.close()
            return status,result
        try:
            for _ in range(100):
                if sock.exists():break
                if child.poll() is not None: self.fail('Web server exited')
                time.sleep(.03)
            self.assertEqual(sock.stat().st_mode & 0o777,0o600)
            self.assertEqual(request('GET','/api/state')[0],200)
            host_status, host_body = request('GET', '/api/host')
            self.assertEqual(host_status, 200)
            host = json.loads(host_body)
            if sys.platform.startswith('linux'):
                self.assertTrue(host['available'])
            else:
                # The UID thread sampler reads Linux /proc. On a Mac release
                # runner the HTTP endpoint must report unavailable, not a
                # successful empty/zero sample.
                self.assertFalse(host['available'])
                self.assertIsNone(host['at'])
            self.assertEqual(request('GET', '/api/host', host='evil.example:8790')[0],403)
            self.assertEqual(request('GET', '/monitor.js')[0],200)
            health_status,health_body=request('GET','/api/health')
            self.assertEqual(health_status,200)
            self.assertEqual(json.loads(health_body)['service'],'gpuq')
            self.assertEqual(json.loads(health_body)['uid'],os.getuid())
            self.assertEqual(request('GET','/api/state',host='evil.example:8790')[0],403)
            self.assertEqual(request('GET','/../gpuqueue/core.py')[0],404)
            path='/api/tasks/'+self.ids[0]+'/start'
            self.assertEqual(request('POST',path,{'digest':'0'*64})[0],403)
            headers={'Content-Type':'application/json','X-GPUQ-Action':'1','Origin':'http://evil.example'}
            self.assertEqual(request('POST',path,{'digest':'0'*64},headers)[0],403)
            self.assertIsNone(self.control.state()['tasks'][0]['approved_at'])
            headers['Origin']='http://127.0.0.1:8790'
            self.assertEqual(request('POST','/api/worker/claim',{},headers)[0],404)
            self.assertEqual(request('POST','/api/submit',{},headers)[0],404)
            self.assertEqual(request('POST',path,{'digest':'0'*64},headers)[0],200)
            self.assertTrue(next(t for t in self.control.state()['tasks'] if t['id']==self.ids[0])['approved_at'])
            stop_path='/api/tasks/'+self.ids[0]+'/stop'
            forbidden={**headers,'Origin':'http://evil.example'}
            self.assertEqual(request('POST',stop_path,{'digest':'0'*64},forbidden)[0],403)
            self.assertEqual(request('POST',stop_path,{'digest':'bad'},headers)[0],409)
            status,body=request('POST',stop_path,{'digest':'0'*64},headers)
            self.assertEqual(status,200)
            stopped=next(t for t in json.loads(body)['tasks'] if t['id']==self.ids[0])
            self.assertEqual(stopped['state'],'cancelled')
            delete_path='/api/tasks/'+self.ids[0]+'/delete'
            self.assertEqual(request('POST',delete_path,{'digest':'0'*64},forbidden)[0],403)
            self.assertEqual(request('POST',delete_path,{'digest':'0'*64},headers)[0],200)
            self.assertNotIn(self.ids[0],[t['id'] for t in self.control.state()['tasks']])
        finally:
            child.terminate();child.wait(timeout=5)

if __name__=='__main__': unittest.main()
