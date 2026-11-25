from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import threading
import tempfile
import time
import unittest
from unittest.mock import patch,Mock
from gpuqueue.core import Store,normalize,atomic_json,read_json,HOME
from gpuqueue.runner import execute
from gpuqueue.control import Control, ControlError
from gpuqueue.service import Service
from gpuqueue.platform import Markflow

class QueueTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=HOME/'scratch')
  self.root=Path(self.temp.name)
  self.project=self.root/'project';self.project.mkdir()
  self.script=self.project/'step.py'
  self.script.write_text("import pathlib,sys,json; pathlib.Path(sys.argv[1]).write_text(json.dumps({'ok':True}))\n")
  self.manifest={'schema_version':1,'title':'test pipeline','project':str(self.project),'code_files':['step.py'],'resources':{'gpus':1,'memory_gb':2,'estimated_hours':1},'steps':[{'name':'first','argv':['/usr/bin/python3','{code}/step.py','{outputs}/one.json'],'outputs':['{outputs}/one.json']},{'name':'second','argv':['/usr/bin/python3','{code}/step.py','{outputs}/two.json'],'outputs':['{outputs}/two.json']}]}
  self.store=Store(self.root/'state')
 def tearDown(self):self.temp.cleanup()
 def task(self):return self.store.submit(self.manifest)[0]
 def approve(self,task):
  folder=self.store.root/'tasks'/task['id']
  atomic_json(folder/'run/approval.json',{'digest':task['digest'],'approved_at':'2026-10-22T00:00:00Z','gpu_uuids':['GPU-test']})
  return folder
 def test_submission_is_immutable_idempotent_and_unapproved(self):
  task,created=self.store.submit(self.manifest);again,second=self.store.submit(self.manifest)
  self.assertTrue(created);self.assertFalse(second);self.assertEqual(task['id'],again['id']);self.assertIsNone(task['internal']['approved_at'])
  self.script.write_text('changed')
  self.assertNotEqual(self.task()['id'],task['id'])
  self.assertIn('import pathlib',(self.store.root/'tasks'/task['id']/'code/step.py').read_text())
 def test_unapproved_service_does_not_call_gpu_or_lark(self):
  self.task();platform=Mock();platform.resources={}
  service=Service({},self.store,platform)
  service.remote=Mock(return_value={'revision':0,'tasks':[]})
  service.tick();platform.refresh.assert_called_once_with(active=False);platform.select.assert_not_called();platform.request.assert_not_called();platform.submit_job.assert_not_called()
 def test_runner_executes_steps_once_and_validates_outputs(self):
  folder=self.approve(self.task())
  with patch('gpuqueue.runner.subprocess.run',return_value=subprocess.CompletedProcess([],0,'GPU-test\n','')):
   self.assertEqual(execute(folder),0)
  status=read_json(folder/'run/status.json');self.assertEqual(status['state'],'completed');self.assertTrue((folder/'outputs/two.json').is_file())
  with self.assertRaises(FileExistsError):execute(folder)
 def test_failure_stops_following_steps(self):
  self.manifest['steps'][0]['argv']=['/usr/bin/python3','-c','import sys;sys.exit(7)']
  folder=self.approve(self.task())
  with patch('gpuqueue.runner.subprocess.run',return_value=subprocess.CompletedProcess([],0,'GPU-test\n','')):
   self.assertEqual(execute(folder),1)
  self.assertFalse((folder/'outputs/two.json').exists());self.assertEqual(len(read_json(folder/'run/status.json')['steps']),1)
 def test_changed_inputs_fail_before_any_step(self):
  data=self.project/'data.txt';data.write_text('first');self.manifest['inputs']=[str(data)]
  folder=self.approve(self.task());data.write_text('second')
  self.assertEqual(execute(folder),1);self.assertEqual(read_json(folder/'run/status.json')['steps'],[])
 def test_remote_digest_mismatch_cannot_approve(self):
  task=self.task();platform=Mock();platform.resources={};service=Service({},self.store,platform)
  service.remote=Mock(return_value={'revision':1,'tasks':[{'id':task['id'],'digest':'bad','approved_at':'now','position':0}]})
  service.sync();self.assertIsNone(self.store.get(task['id'])['internal']['approved_at'])
 def test_gpu_selection_requires_sustained_low_use_and_memory(self):
  task=self.task();running=self.task();running['internal']['dispatched_at']=time.time()-600
  adapter=Markflow(self.store,{'username':'linlishuo'})
  resource={'id':'test','status':'online','type':'H卡离线','telemetry':{'at':time.time(),'gpus':[{'uuid':'GPU-test','total_mb':81920,'used_mb':1024,'utilization':10}],'apps':[]},'samples':[{'at':time.time()-300+i*30,'utilization':10} for i in range(11)]}
  adapter.resources={'test':resource}
  self.assertIsNotNone(adapter.select(task,[running])[0])
  resource['samples'][2]['utilization']=80;self.assertIsNone(adapter.select(task,[running])[0])
  resource['samples'][2]['utilization']=10;resource['telemetry']['gpus'][0]['used_mb']=81000;self.assertIsNone(adapter.select(task,[running])[0])
 def test_ambiguous_request_is_never_resubmitted(self):
  task=self.task();task['internal']['approved_at']='now';adapter=Markflow(self.store,{'username':'linlishuo'})
  adapter.resources={'existing':{'status':'unknown'}};adapter.lark=Mock()
  self.assertIsNone(adapter.request(task));adapter.lark.assert_not_called()
 def test_reuse_an_idle_card_even_when_another_card_is_busy(self):
  task=self.task();adapter=Markflow(self.store,{'username':'linlishuo'})
  gpu=lambda uid:{'uuid':uid,'total_mb':81920,'used_mb':1024,'utilization':5}
  adapter.resources={'r':{'id':'r','status':'online','type':'H卡离线','telemetry':{'at':time.time(),'gpus':[gpu('GPU-busy'),gpu('GPU-free')],'apps':[['GPU-busy','999']]}}}
  self.assertEqual(adapter.select(task,[])[0][1],['GPU-free'])
 def test_a_closed_prior_allocation_does_not_close_the_new_pending_one(self):
  adapter=Markflow(self.store,{'username':'linlishuo','home':str(self.root)})
  uid='11111111-1111-4111-8111-111111111111';folder=self.root/'.local/state/markflow-gpu-requests'/uid
  atomic_json(folder/'request.json',{'fields':{'服务器用户名':'linlishuo','资源类型':'H卡离线','卡数':1}})
  atomic_json(folder/'state.json',{'state':'submitted','request':uid,'prior_resource_state':'user_confirmed_reclaimed'})
  adapter.discover();self.assertEqual(adapter.resources[uid]['status'],'pending')
 def test_snapshot_entrypoint_must_exist(self):
  self.manifest['steps'][0]['argv'][1]='{code}/missing.py'
  with self.assertRaises(ValueError):self.task()
 def test_dispatch_crash_reconciles_existing_job_without_resubmit(self):
  task=self.task();request='11111111-1111-4111-8111-111111111111';argv=['/usr/bin/python3','/unique-runner']
  task['internal'].update(dispatch='submitting',request_uuid=request,argv=argv)
  adapter=Markflow(self.store,{'username':'linlishuo','home':str(self.root)})
  job='22222222-2222-4222-8222-222222222222';atomic_json(adapter.job_folder(request)/(job+'.json'),{'argv':argv})
  adapter.submit_job=Mock();service=Service({},self.store,adapter);service.refresh_task(task)
  self.assertEqual(task['internal']['job_uuid'],job);adapter.submit_job.assert_not_called()

 def test_each_successful_dispatch_starts_sampling_after_compute_receipt_is_saved(self):
  task=self.task();task['internal']['approved_at']='browser approval';self.store.save(task)
  request='11111111-1111-4111-8111-111111111111'
  compute='22222222-2222-4222-8222-222222222222';probe='33333333-3333-4333-8333-333333333333'
  adapter=Markflow(self.store,{'username':'linlishuo','home':str(self.root)})
  resource={'id':request,'status':'online','probe_checked':time.time(),'telemetry':{'at':time.time(),'gpus':[]}}
  adapter.resources={request:resource};adapter.submit_job=Mock(side_effect=[compute,probe])
  service=Service({},self.store,adapter);service.remote=Mock()
  service.dispatch(task,(resource,['GPU-test']))
  saved=self.store.get(task['id'])
  self.assertEqual(saved['internal']['job_uuid'],compute)
  self.assertEqual(saved['internal']['dispatch'],'submitted')
  self.assertEqual(resource['probe']['job'],probe)
  self.assertEqual(resource['sampling_start']['task'],task['id'])
  self.assertEqual(adapter.submit_job.call_count,2)
  service.dispatch(task,(resource,['GPU-test']))
  self.assertEqual(adapter.submit_job.call_count,2)

 def release_service(self):
  adapter=Markflow(self.store,{'username':'linlishuo','home':str(self.root)})
  rid='11111111-1111-4111-8111-111111111111'
  adapter.resources={rid:{'id':rid,'status':'online','owned_by_gpuq':True,'release_when_done':True}}
  adapter.run=Mock()
  self.store.metadata('resource_policy',{'release_when_queue_idle':True,'release_interface':'unavailable'})
  return Service({},self.store,adapter),adapter,rid
 def test_release_intent_waits_for_all_approved_tasks_and_is_not_a_release(self):
  service,adapter,rid=self.release_service();first=self.task()
  first['internal']['approved_at']='now';first['public']['state']='completed'
  self.manifest['title']='second task';second=self.task();second['internal']['approved_at']='now';second['public']['state']='queued'
  service.record_release_intents([first,second]);self.assertEqual(adapter.resources[rid]['release']['state'],'armed')
  second['public']['state']='completed';service.record_release_intents([first,second])
  intent=read_json(self.store.root/'release-intents'/(rid+'.json'))
  self.assertEqual(intent['state'],'pending_interface');self.assertFalse(intent['released'])
  self.assertEqual(adapter.resources[rid]['status'],'online');adapter.run.assert_not_called()
  service.record_release_intents([first,second]);self.assertEqual(intent,read_json(self.store.root/'release-intents'/(rid+'.json')))
 def test_unapproved_tasks_do_not_hold_a_card(self):
  service,adapter,rid=self.release_service();task=self.task()
  service.record_release_intents([task]);self.assertEqual(adapter.resources[rid]['release']['state'],'pending_interface')
 def test_uncertain_execution_or_submission_does_not_mark_queue_done(self):
  service,adapter,rid=self.release_service();task=self.task();task['internal']['approved_at']='now'
  task['public']['state']='execution_unknown';service.record_release_intents([task]);self.assertEqual(adapter.resources[rid]['release']['state'],'armed')
  task['public']['state']='blocked';task['internal']['dispatch']='unknown';service.record_release_intents([task]);self.assertEqual(adapter.resources[rid]['release']['state'],'armed')
 def test_only_service_owned_resources_get_release_intents(self):
  service,adapter,rid=self.release_service();adapter.resources[rid]['owned_by_gpuq']=False
  service.record_release_intents([]);self.assertNotIn('release',adapter.resources[rid])
  self.assertFalse((self.store.root/'release-intents'/(rid+'.json')).exists())

 def h100_adapter(self):
  adapter=Markflow(self.store,{'username':'linlishuo'})
  resource={'id':'test','status':'online','type':'H卡离线','telemetry':{'at':time.time(),'gpus':[{'uuid':'GPU-H100','total_mb':81559,'used_mb':1,'utilization':0}],'apps':[]},'samples':[{'at':time.time()-300+i*30,'utilization':0} for i in range(11)]}
  adapter.resources={'test':resource}
  return adapter,resource
 def test_80_decimal_gb_task_fits_idle_h100_with_serial_runtime_reserve(self):
  task=self.task();task['doc']['resources']['memory_gb']=80
  adapter,resource=self.h100_adapter()
  self.assertEqual(adapter.select(task,[])[0][1],['GPU-H100'])
  task['internal']['approved_at']='browser approval';adapter.lark=Mock()
  self.assertIsNone(adapter.request(task));adapter.lark.assert_not_called()
 def test_h100_memory_gate_still_rejects_insufficient_free_memory(self):
  task=self.task();task['doc']['resources']['memory_gb']=80
  adapter,resource=self.h100_adapter();resource['telemetry']['gpus'][0]['used_mb']=6000
  selection,reason=adapter.select(task,[]);self.assertIsNone(selection);self.assertIn('GPU 已就绪',reason)
  resource['telemetry']['gpus'][0]['used_mb']=1;task['doc']['resources']['memory_gb']=86
  self.assertIsNone(adapter.select(task,[])[0])
 def test_parallel_admission_keeps_the_larger_shared_memory_margin(self):
  task=self.task();task['doc']['resources']['memory_gb']=80
  adapter,resource=self.h100_adapter();running=self.task();running['internal']['dispatched_at']=time.time()-600
  self.assertIsNone(adapter.select(task,[running])[0])

class SubmissionDeleteTests(unittest.TestCase):
    """Deleted versions stay deleted across CLI submissions and transaction races."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        home_patch = patch('gpuqueue.core.HOME', self.home)
        home_patch.start()
        self.addCleanup(home_patch.stop)
        project = self.home / 'project'
        project.mkdir()
        (project / 'step.py').write_text('print("fixture")\n')
        self.manifest = {
            'title': 'submission fixture', 'project': str(project),
            'code_files': ['step.py'],
            'steps': [{'argv': [sys.executable, '{code}/step.py']}],
        }
        self.manifest_path = self.home / 'manifest.json'
        self.store = Store(self.home / '.local/state/gpuq')

    def cli_submit(self):
        self.manifest_path.write_text(json.dumps(self.manifest))
        return subprocess.run(
            [sys.executable, '-m', 'gpuqueue.cli', 'submit',
             '--manifest', str(self.manifest_path), '--source', 'Codex'],
            env={**os.environ, 'HOME': str(self.home)},
            capture_output=True, text=True, timeout=20,
        )

    def snapshot(self):
        with self.store.connect() as db:
            database = list(db.iterdump())
        files = {
            str(p.relative_to(self.store.root)): (
                p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
            for p in (self.store.root / 'tasks').rglob('*') if p.is_file()
        }
        return database, files

    def assert_cli_rejected(self):
        before = self.snapshot()
        result = self.cli_submit()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, '')
        error = json.loads(result.stderr)
        self.assertFalse(error['ok'])
        self.assertEqual(error['error'],
                         '这一版任务已删除，请修改 submission_key 或清单内容后重新提交')
        self.assertNotIn('http://', result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_cli_first_submission_and_visible_duplicate_without_control_tables(self):
        # Also represents old CLI-only databases with tasks/meta but no Control.
        for created in [True, False]:
            result = self.cli_submit()
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertTrue(receipt['ok'])
            self.assertEqual(receipt['created'], created)
            self.assertEqual(receipt['state'], 'ready')
            if created:
                task_id = receipt['task_id']
            self.assertEqual(receipt['task_id'], task_id)
        self.assertIsNone(self.store.get(task_id)['internal']['approved_at'])
        with self.store.connect() as db:
            self.assertIsNone(db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='task_deletions'").fetchone())

    def check_deleted_submission(self, state):
        task, _ = self.store.submit(self.manifest)
        control = Control(self.store)
        platform = Mock()
        platform.resources = {}
        service = Service({}, self.store, platform)
        if state != 'ready':
            control.start(task['id'], task['digest'])
            if state == 'synced':
                service.sync()
            if state == 'claimed':
                control.claim(task['id'], task['digest'], control.state()['revision'])
            control.stop(task['id'], task['digest'])
            if state == 'claimed':
                control.confirm_stop(task['id'], task['digest'])
        folder = self.store.root / 'tasks' / task['id']
        (folder / 'run/output.log').write_text('retained log')
        (folder / 'outputs/result.txt').write_text('retained output')
        control.delete(task['id'], task['digest'])
        self.assert_cli_rejected()
        self.assertEqual(control.state()['tasks'], [])
        with self.assertRaises(ControlError):
            control.start(task['id'], task['digest'])
        # Even an approval not yet seen by the scheduler must not start work.
        service.tick()
        platform.request.assert_not_called()
        platform.submit_job.assert_not_called()
        self.assertEqual(control.state()['tasks'], [])

    def test_cli_rejects_deleted_ready_task(self):
        self.check_deleted_submission('ready')

    def test_cli_rejects_deleted_approval_before_scheduler_sync(self):
        self.check_deleted_submission('unsynced')

    def test_cli_rejects_deleted_approval_after_scheduler_sync(self):
        self.check_deleted_submission('synced')

    def test_cli_rejects_deleted_claimed_and_confirmed_stopped_task(self):
        self.check_deleted_submission('claimed')

    def test_new_submission_key_creates_ready_version_requiring_new_approval(self):
        old, _ = self.store.submit(self.manifest)
        control = Control(self.store)
        control.start(old['id'], old['digest'])
        control.stop(old['id'], old['digest'])
        control.delete(old['id'], old['digest'])
        self.manifest['submission_key'] = 'second-version'
        result = self.cli_submit()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt['created'])
        self.assertNotEqual(receipt['task_id'], old['id'])
        task = self.store.get(receipt['task_id'])
        self.assertEqual(task['public']['state'], 'ready')
        self.assertIsNone(task['internal']['approved_at'])
        self.assertIsNone(task['internal']['dispatch'])
        visible = control.state()['tasks']
        self.assertEqual([t['id'] for t in visible], [task['id']])
        self.assertIsNone(visible[0]['approved_at'])
        with self.assertRaises(ControlError):
            control.claim(task['id'], task['digest'], control.state()['revision'])

    def race(self, *, existing=False, delete=True):
        """Pause the losing submit before lookup or during snapshot preparation.

        The other connection creates/deletes and commits before releasing it.
        No sleeps or timing-dependent winner selection are used.
        """
        control = Control(self.store)
        if existing:
            task, _ = self.store.submit(self.manifest)
        paused, resume = threading.Event(), threading.Event()
        main_thread = threading.current_thread()
        connect, copy = self.store.connect, shutil.copy2

        def wait_for_commit():
            if threading.current_thread() is not main_thread and not paused.is_set():
                paused.set()
                if not resume.wait(10):
                    raise TimeoutError('competing transaction did not complete')

        def gated_connect():
            wait_for_commit()
            return connect()

        def gated_copy(*args, **kwargs):
            wait_for_commit()
            return copy(*args, **kwargs)

        target = (patch.object(self.store, 'connect', side_effect=gated_connect)
                  if existing else patch('gpuqueue.core.shutil.copy2', side_effect=gated_copy))
        with target, ThreadPoolExecutor(max_workers=1) as pool:
            losing = pool.submit(self.store.submit, self.manifest)
            try:
                self.assertTrue(paused.wait(10), 'submit did not reach barrier')
                if not existing:
                    task, created = self.store.submit(self.manifest)
                    self.assertTrue(created)
                if delete:
                    control.delete(task['id'], task['digest'])
                before = self.snapshot()
            finally:
                resume.set()
            if delete:
                with self.assertRaisesRegex(ValueError, '已删除.*submission_key'):
                    losing.result(timeout=10)
            else:
                duplicate, created = losing.result(timeout=10)
                self.assertEqual(duplicate, task)
                self.assertFalse(created)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(list((self.store.root / 'tasks').glob('.prepare-*')))

    def test_deletion_committed_before_existing_task_lookup_is_rejected(self):
        self.race(existing=True)

    def test_concurrent_insert_then_delete_before_final_submission_is_rejected(self):
        self.race()

    def test_concurrent_visible_insert_returns_existing_task_created_false(self):
        self.race(delete=False)


if __name__=='__main__':unittest.main()
