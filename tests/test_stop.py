"""Cancellation integration with isolated CPU-only processes, never real GPU jobs."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock
import uuid
from gpuqueue.core import HOME,Store,atomic_json,read_json
from gpuqueue.control import Control,ControlError,QueueChanged
from gpuqueue.service import Service
from gpuqueue import stop_control as stop

class StopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=HOME/'scratch',prefix='stop-qa-')
        self.root=Path(self.temp.name);self.project=self.root/'code';self.project.mkdir()
        (self.project/'step.py').write_text('print("CPU test only")\n')
        self.store=Store(self.root/'state');self.control=Control(self.store)
        self.task=self.store.submit({'title':'stop QA','project':str(self.project),'code_files':['step.py'],'steps':[{'name':'CPU dummy','argv':['/usr/bin/python3','{code}/step.py']}]})[0]
        self.folder=self.store.root/'tasks'/self.task['id'];self.processes=[]
    def tearDown(self):
        for process in self.processes:
            if process.poll() is None: process.kill()
            process.wait(timeout=5)
        self.temp.cleanup()
    def approve_claim(self):
        state=self.control.start(self.task['id'],self.task['digest'])
        self.control.claim(self.task['id'],self.task['digest'],state['revision'])
    def cpu_tree(self):
        # Replace only this private fixture's dummy runner, not any real snapshot.
        path=self.folder/'runner.py';path.chmod(0o600)
        path.write_text('''import subprocess,sys,time,pathlib,os
folder=pathlib.Path(sys.argv[1])
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)'],start_new_session=True)
(folder/'run/child.pid').write_text(str(child.pid))
(folder/'outputs/kept.txt').write_text('existing result')
while True:time.sleep(.1)
''')
        argv=['/usr/bin/python3','-I',str(path),str(self.folder)]
        env=dict(os.environ,GPUQ_TASK_ID=self.task['id'],GPUQ_OUTPUT_DIR=str(self.folder/'outputs'))
        p=subprocess.Popen(argv,env=env);self.processes.append(p)
        for _ in range(100):
            if (self.folder/'run/child.pid').exists():break
            time.sleep(.02)
        self.assertTrue((self.folder/'run/child.pid').exists())
        child=int((self.folder/'run/child.pid').read_text())
        return p,child,argv
    def test_stop_is_version_bound_idempotent_and_blocks_stale_dispatch(self):
        state=self.control.start(self.task['id'],self.task['digest'])
        with self.assertRaises(ControlError):self.control.stop(self.task['id'],'wrong')
        first=self.control.stop(self.task['id'],self.task['digest'])
        second=self.control.stop(self.task['id'],self.task['digest'])
        self.assertEqual(first,second);self.assertEqual(first['tasks'][0]['state'],'cancelled')
        with self.assertRaises(QueueChanged):self.control.claim(self.task['id'],self.task['digest'],state['revision'])
        with self.assertRaises(ControlError):self.control.start(self.task['id'],self.task['digest'])
        with self.store.connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM queue_audit WHERE action LIKE 'browser_stop:%'").fetchone()[0],1)
    def test_claimed_task_stays_stopping_until_confirmed(self):
        self.approve_claim();state=self.control.stop(self.task['id'],self.task['digest'])
        self.assertEqual(state['tasks'][0]['state'],'stopping')
        with self.assertRaises(QueueChanged):self.control.claim(self.task['id'],self.task['digest'],state['revision'])
        self.control.confirm_stop(self.task['id'],self.task['digest'])
        self.assertEqual(self.control.state()['tasks'][0]['state'],'stopped')
    def test_queued_stop_cannot_apply_for_gpu_or_submit_a_job(self):
        self.control.start(self.task['id'],self.task['digest']);self.control.stop(self.task['id'],self.task['digest'])
        platform=Mock();platform.resources={};service=Service({},self.store,platform)
        service.tick();platform.request.assert_not_called();platform.submit_job.assert_not_called();platform.select.assert_not_called()
        self.assertEqual(self.store.get(self.task['id'])['public']['state'],'cancelled')
    @unittest.skipUnless(hasattr(os,'pidfd_open') and hasattr(signal,'pidfd_send_signal'),'pidfds unavailable')
    def test_legacy_stop_kills_its_tree_but_preserves_unrelated_process_and_outputs(self):
        self.approve_claim();p,child,argv=self.cpu_tree()
        unrelated=subprocess.Popen(['/usr/bin/python3','-c','import time;time.sleep(300)']);self.processes.append(unrelated)
        self.control.stop(self.task['id'],self.task['digest'])
        request,job=str(uuid.uuid4()),str(uuid.uuid4());jobs=self.root/'jobs';jobs.mkdir()
        atomic_json(jobs/(job+'.json'),{'argv':argv});atomic_json(jobs/job/'status.json',{'state':'running','pid':p.pid,'at':time.time()})
        proof=stop.stop_legacy(self.folder,request,job,jobs_root=jobs)
        p.wait(timeout=5);self.assertIsNone(stop.identity(child));self.assertIsNone(unrelated.poll())
        self.assertEqual(proof['state'],'stopped');self.assertEqual((self.folder/'outputs/kept.txt').read_text(),'existing result')
        self.assertFalse((self.folder/'outputs/next-step.txt').exists())
    @unittest.skipUnless(hasattr(os,'pidfd_open') and hasattr(signal,'pidfd_send_signal'),'pidfds unavailable')
    def test_pid_or_command_mismatch_is_not_signalled(self):
        self.approve_claim();p,child,argv=self.cpu_tree();self.control.stop(self.task['id'],self.task['digest'])
        other=subprocess.Popen(['/usr/bin/python3','-c','import time;time.sleep(300)']);self.processes.append(other)
        request,job=str(uuid.uuid4()),str(uuid.uuid4());jobs=self.root/'jobs';jobs.mkdir()
        atomic_json(jobs/(job+'.json'),{'argv':argv});atomic_json(jobs/job/'status.json',{'state':'running','pid':other.pid,'at':time.time()})
        with self.assertRaises(stop.StopError):stop.stop_legacy(self.folder,request,job,jobs_root=jobs)
        self.assertIsNone(p.poll());self.assertIsNone(other.poll())
        # Explicit fixture cleanup of its own detached child.
        value=stop.identity(child)
        if value:stop.send(value,signal.SIGKILL)
    @unittest.skipUnless(hasattr(os,'pidfd_open') and hasattr(signal,'pidfd_send_signal'),'pidfds unavailable')
    def test_new_supervisor_stops_current_step_without_mutating_snapshot(self):
        # CPU stand-in for a frozen runner, used only in this isolated test.
        path=self.folder/'runner.py';path.chmod(0o600)
        path.write_text('import pathlib,sys,time\np=pathlib.Path(sys.argv[1]);(p/"outputs/kept.txt").write_text("saved")\ntime.sleep(30)\n(p/"outputs/next-step.txt").write_text("must not run")\n')
        before=path.read_bytes();control=self.folder/'run/stop-control.py';shutil.copyfile(Path(stop.__file__),control)
        atomic_json(self.folder/'run/dispatch.json',{'request':'fixture-request','job':'fixture-job'})
        p=subprocess.Popen(['/usr/bin/python3','-I',str(control),'supervise',str(self.folder)]);self.processes.append(p)
        for _ in range(100):
            if (self.folder/'outputs/kept.txt').exists():break
            time.sleep(.02)
        self.approve_claim();self.control.stop(self.task['id'],self.task['digest'])
        self.assertEqual(p.wait(timeout=10),0)
        proof=read_json(self.folder/'run/stop-result.json');self.assertEqual(proof['state'],'stopped')
        self.assertEqual(path.read_bytes(),before);self.assertEqual((self.folder/'outputs/kept.txt').read_text(),'saved')
        self.assertFalse((self.folder/'outputs/next-step.txt').exists())
    def test_unverified_result_never_becomes_stopped(self):
        self.approve_claim();state=self.control.stop(self.task['id'],self.task['digest']);at=state['tasks'][0]['stop_requested_at']
        task=self.store.get(self.task['id']);task['internal'].update(stop_requested_at=at,request_uuid='r',job_uuid='j',dispatch='submitted');task['public']['state']='stopping';self.store.save(task)
        atomic_json(self.folder/'run/stop-result.json',{'state':'unverified','task':task['id'],'digest':task['digest'],'stop_at':at,'uid':os.getuid(),'request':'r','job':'j','error':'identity mismatch'})
        platform=Mock();platform.resources={};service=Service({},self.store,platform);service.process_stop(task)
        self.assertEqual(self.control.state()['tasks'][0]['state'],'stopping');platform.submit_job.assert_not_called()

    def test_service_submits_one_control_job_and_requires_matching_proof(self):
        self.approve_claim();state=self.control.stop(self.task['id'],self.task['digest']);at=state['tasks'][0]['stop_requested_at']
        request,job,control_job=[str(uuid.uuid4()) for _ in range(3)]
        task=self.store.get(self.task['id']);task['internal'].update(approved_at='browser',stop_requested_at=at,request_uuid=request,job_uuid=job,dispatch='submitted');task['public']['state']='stopping';self.store.save(task)
        jobs=self.root/'jobs';jobs.mkdir()
        platform=Mock();platform.resources={};platform.job_folder.return_value=jobs;platform.submit_job.return_value=control_job
        service=Service({},self.store,platform);service.process_stop(task)
        platform.submit_job.assert_called_once()
        command=platform.submit_job.call_args.args[1]
        self.assertIn('stop',command);self.assertIn(request,command);self.assertIn(job,command)
        Service({},self.store,platform).process_stop(self.store.get(task['id']))
        platform.submit_job.assert_called_once()
        proof={'state':'stopped','mode':'legacy','task':task['id'],'digest':task['digest'],'stop_at':at,'uid':os.getuid(),'request':request,'job':job,'processes':[]}
        atomic_json(self.folder/'run/stop-result.json',{**proof,'digest':'wrong version'})
        service.process_stop(self.store.get(task['id']));self.assertEqual(self.control.state()['tasks'][0]['state'],'stopping')
        atomic_json(self.folder/'run/stop-result.json',proof)
        service.process_stop(self.store.get(task['id']));self.assertEqual(self.control.state()['tasks'][0]['state'],'stopped')
        atomic_json(self.folder/'run/status.json',{'state':'running','stage':0,'started_at':time.time(),'updated_at':time.time(),'steps':[{'name':'CPU dummy','state':'running'}]})
        service.refresh_task(self.store.get(task['id']))
        self.assertEqual(self.store.get(task['id'])['public']['state'],'stopped')
        self.assertEqual(self.store.get(task['id'])['public']['step_records'][0]['state'],'stopped')

    def test_supervised_task_gets_time_to_confirm_before_legacy_fallback(self):
        self.approve_claim();state=self.control.stop(self.task['id'],self.task['digest']);at=state['tasks'][0]['stop_requested_at']
        task=self.store.get(self.task['id']);task['internal'].update(approved_at='browser',stop_requested_at=at,request_uuid='r',job_uuid='j',dispatch='submitted',argv=['/usr/bin/python3','-I',str(self.folder/'run/stop-control.py'),'supervise',str(self.folder)]);task['public']['state']='stopping';self.store.save(task)
        platform=Mock();platform.resources={};service=Service({},self.store,platform);service.process_stop(task)
        platform.submit_job.assert_not_called();self.assertEqual(self.control.state()['tasks'][0]['state'],'stopping')

if __name__=='__main__':unittest.main()
