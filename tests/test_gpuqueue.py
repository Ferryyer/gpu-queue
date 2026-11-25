import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch,Mock
from gpuqueue.core import Store,normalize,atomic_json,read_json,HOME,canonical
from gpuqueue.control import Control
from gpuqueue.runner import execute
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

class ServiceRefreshTests(unittest.TestCase):
 def setUp(self):
  self.temp = tempfile.TemporaryDirectory()
  self.addCleanup(self.temp.cleanup)
  self.queue('queue')

 def queue(self, name):
  self.store = Store(Path(self.temp.name)/name)
  self.control = Control(self.store)
  self.platform = Mock()
  self.platform.resources = {}
  self.platform.job_folder.return_value = self.store.root/'jobs'
  self.service = Service({}, self.store, self.platform)

 def task(self, state, **internal):
  index = len(self.store.tasks())+1
  task_id = 'GQ-'+str(index).zfill(16)
  public = {'id':task_id, 'state':state, 'events':[], 'checks':['pending']}
  internal = {'position':0, **internal}
  with self.store.connect() as db:
   db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',
              (task_id, str(index)*64, canonical({'project':self.temp.name}), canonical(public), canonical(internal)))
  return self.store.get(task_id)

 def status(self, task, state='running', **extra):
  atomic_json(self.store.root/'tasks'/task['id']/'run/status.json',
              {'state':state, 'started_at':1000, 'updated_at':1000, 'steps':[], **extra})

 def test_tick_skips_terminal_files_and_saves_but_refreshes_active_task(self):
  history = [self.task(state, request_uuid='r', job_uuid='j', dispatch='submitted', terminal_reconciled=True)
             for state in ['completed', 'failed', 'interrupted', 'cancelled', 'stopped']]
  deleted = self.task('completed', request_uuid='r', job_uuid='j', dispatch='submitted')
  self.control.delete(deleted['id'], deleted['digest'])
  history.append(deleted)
  active = self.task('dispatching', request_uuid='r', job_uuid='j', dispatch='submitted')
  self.status(active)
  original_read = read_json
  def read_active_only(path, *args):
   self.assertFalse(any(t['id'] in Path(path).parts for t in history))
   return original_read(path, *args)
  with patch('gpuqueue.service.read_json', side_effect=read_active_only), \
       patch.object(self.store, 'save', wraps=self.store.save) as save, \
       patch('gpuqueue.service.time.time', return_value=1000):
   self.service.tick()
  self.assertEqual([call.args[0]['id'] for call in save.call_args_list], [active['id']])
  self.assertEqual(self.store.get(active['id'])['public']['state'], 'running')
  self.platform.refresh.assert_called_once_with(active=True)
  self.platform.submit_job.assert_not_called()

 def test_unchanged_active_refresh_and_both_cycle_syncs_do_not_save(self):
  task = self.task('dispatching', request_uuid='r', job_uuid='j', dispatch='submitted')
  self.task('ready')
  self.status(task, steps=[{'state':'running'}])
  log = self.store.root/'tasks'/task['id']/'run/step-0.log'
  log.write_text('first log')
  with patch('gpuqueue.service.time.time', return_value=1000):
   self.service.cycle()
   with patch.object(self.store, 'save', wraps=self.store.save) as save:
    self.service.cycle()
   save.assert_not_called()
   log.write_text('new log')
   with patch.object(self.store, 'save', wraps=self.store.save) as save:
    self.service.tick()
   save.assert_called_once()
  self.assertEqual(self.store.get(task['id'])['public']['step_records'][0]['log'], 'new log')

 def test_sync_saves_browser_changes_once_and_rejects_stale_digest(self):
  task = self.task('ready')
  self.control.start(task['id'], task['digest'])
  with patch.object(self.store, 'save', wraps=self.store.save) as save:
   self.service.sync()
   self.service.sync()
  save.assert_called_once()
  saved = self.store.get(task['id'])
  self.assertTrue(saved['internal']['approved_at'])
  self.assertEqual(saved['public']['state'], 'queued')
  self.assertEqual(len(saved['public']['events']), 1)
  self.service.remote = Mock(return_value={'revision':2, 'tasks':[
   {'id':task['id'], 'digest':'stale', 'position':99, 'stop_requested_at':'later'}]})
  with patch.object(self.store, 'save', wraps=self.store.save) as save:
   self.service.sync()
  save.assert_not_called()
  self.assertEqual(self.store.get(task['id']), saved)

 def test_blocked_and_terminal_ambiguous_dispatch_reconcile_late_receipt(self):
  for state, dispatch in [('blocked', 'unknown'), ('failed', 'submitting')]:
   with self.subTest(state=state):
    argv = ['unique-runner', state]
    task = self.task(state, request_uuid='r', dispatch=dispatch, argv=argv)
    self.service.tick()  # No receipt yet; retain the uncertain submission.
    self.assertEqual(self.store.get(task['id'])['internal']['dispatch'], 'unknown')
    atomic_json(self.platform.job_folder('r')/(state+'.json'), {'argv':argv})
    self.status(task, updated_at=time.time())
    self.service.tick()
    saved = self.store.get(task['id'])
    self.assertEqual(saved['internal']['job_uuid'], state)
    self.assertEqual(saved['public']['state'], 'running')
  self.platform.request.assert_not_called()
  self.platform.submit_job.assert_not_called()

 def test_unchanged_unresolved_receipt_does_not_save(self):
  task = self.task('blocked', request_uuid='r', dispatch='unknown', argv=['runner'])
  self.service.tick()
  with patch.object(self.store, 'save', wraps=self.store.save) as save:
   self.service.tick()
  save.assert_not_called()
  self.assertEqual(self.store.get(task['id'])['public']['state'], 'blocked')

 def test_blocked_and_execution_unknown_with_jobs_still_observe_completion(self):
  for state in ['blocked', 'execution_unknown']:
   with self.subTest(state=state):
    task = self.task(state, request_uuid='r', job_uuid='j', dispatch='submitted')
    self.status(task, 'completed', finished_at=1060)
    self.service.tick()
    saved = self.store.get(task['id'])
    self.assertEqual(saved['public']['state'], 'completed')
    self.assertTrue(saved['internal']['finished_recorded'])
    with patch.object(self.store, 'save', wraps=self.store.save) as save:
     self.service.tick()
    save.assert_not_called()

 def test_terminal_with_pending_stop_still_checks_matching_proof(self):
  task = self.task('ready')
  state = self.control.start(task['id'], task['digest'])
  self.control.claim(task['id'], task['digest'], state['revision'])
  state = self.control.stop(task['id'], task['digest'])
  at = state['tasks'][0]['stop_requested_at']
  task['internal'].update(request_uuid='r', job_uuid='j', dispatch='submitted', stop_requested_at=at)
  task['public']['state'] = 'failed'
  self.store.save(task)
  self.status(task, 'failed', finished_at=1060)
  proof_path = self.store.root/'tasks'/task['id']/'run/stop-result.json'
  proof = {'task':task['id'], 'digest':'wrong', 'stop_at':at, 'uid':os.getuid(),
           'request':'r', 'job':'j', 'state':'stopped'}
  atomic_json(proof_path, proof)
  task['internal']['stop_dispatch'] = 'submitted'
  self.store.save(task)
  self.service.tick()
  self.assertFalse(self.store.get(task['id'])['internal'].get('stop_confirmed'))
  atomic_json(proof_path, {**proof, 'digest':task['digest']})
  self.service.tick()
  saved = self.store.get(task['id'])
  self.assertTrue(saved['internal']['stop_confirmed'])
  self.assertEqual(saved['public']['state'], 'stopped')
  self.service = Service({}, self.store, self.platform)  # Restart retains the settled state.
  with patch.object(self.store, 'save', wraps=self.store.save) as save, \
       patch('gpuqueue.service.read_json', side_effect=AssertionError('settled task read')), \
       patch('gpuqueue.service.atomic_json', side_effect=AssertionError('settled stop marker write')):
   self.service.tick()
  save.assert_not_called()
  self.platform.submit_job.assert_not_called()

 def assert_settled_completion(self, task):
  saved = self.store.get(task['id'])
  self.assertEqual(saved['public']['state'], 'completed')
  self.assertTrue(saved['internal']['finished_recorded'])
  self.assertEqual(saved['public']['step_records'][0]['outputs'][0]['name'], 'result.json')
  self.assertEqual(saved['public']['step_records'][0]['log'], 'final log')
  self.assertEqual(saved['public']['events'].count('全部步骤成功完成'), 1)
  self.assertEqual(self.control.state()['tasks'][0]['state'], 'completed')
  self.service = Service({}, self.store, self.platform)
  with patch.object(self.store, 'save', wraps=self.store.save) as save, \
       patch('gpuqueue.service.read_json', side_effect=AssertionError('settled task read')):
   self.service.tick()
  save.assert_not_called()
  self.platform.request.assert_not_called()
  self.platform.submit_job.assert_not_called()

 def complete(self, task):
  self.status(task, 'completed', finished_at=1060, steps=[
   {'state':'completed', 'outputs':[{'name':'result.json', 'size':2}]}])
  (self.store.root/'tasks'/task['id']/'run/step-0.log').write_text('final log')

 def test_stop_proof_after_initial_status_read_retains_natural_completion(self):
  task = self.task('ready')
  state = self.control.start(task['id'], task['digest'])
  self.control.claim(task['id'], task['digest'], state['revision'])
  state = self.control.stop(task['id'], task['digest'])
  at = state['tasks'][0]['stop_requested_at']
  task['internal'].update(request_uuid='r', job_uuid='j', dispatch='submitted')
  task['public']['state'] = 'running'
  self.store.save(task)
  self.status(task)
  proof_path = self.store.root/'tasks'/task['id']/'run/stop-result.json'
  reads = []
  def finish_before_stop_proof(path, *args):
   reads.append(Path(path))
   if Path(path) == proof_path:
    self.complete(task)  # Runner exits after tick's first status snapshot.
    atomic_json(proof_path, {'task':task['id'], 'digest':task['digest'],
                'stop_at':at, 'uid':os.getuid(), 'request':'r', 'job':'j', 'state':'stopped'})
   return read_json(path, *args)
  with patch('gpuqueue.service.read_json', side_effect=finish_before_stop_proof), \
       patch('gpuqueue.service.time.time', return_value=1000):
   self.service.tick()
  status_path = self.store.root/'tasks'/task['id']/'run/status.json'
  self.assertLess(reads.index(status_path), reads.index(proof_path))
  self.assert_settled_completion(task)

 def test_job_exit_after_missing_status_read_retains_final_result(self):
  for exit_state in ['finished', 'failed', 'closed']:
   with self.subTest(exit_state=exit_state):
    # Each subcase has an independent queue so UI assertions cover the same task.
    self.queue(exit_state)
    task = self.task('dispatching', request_uuid='r', job_uuid='j', dispatch='submitted')
    status_path = self.store.root/'tasks'/task['id']/'run/status.json'
    job_path = self.platform.job_folder('r')/'j/status.json'
    status_reads = []
    def finish_before_job_receipt(path, *args):
     if Path(path) == job_path:
      self.complete(task)  # The first execution-status read returned None.
      if exit_state == 'closed':
       self.platform.resources = {'r':{'status':'closed'}}
      else:
       atomic_json(job_path, {'state':exit_state})
     value = read_json(path, *args)
     if Path(path) == status_path:
      status_reads.append(value)
     return value
    with patch('gpuqueue.service.read_json', side_effect=finish_before_job_receipt):
     self.service.tick()
    self.assertIsNone(status_reads[0])
    self.assert_settled_completion(task)

 def legacy_terminal(self, state):
  self.queue(state)
  task = self.task('ready', request_uuid='r', job_uuid='j', dispatch='submitted')
  if state == 'stopped':
   started = self.control.start(task['id'], task['digest'])
   self.control.claim(task['id'], task['digest'], started['revision'])
   stopped = self.control.stop(task['id'], task['digest'])
   self.control.confirm_stop(task['id'], task['digest'])
   task['internal'].update(stop_requested_at=stopped['tasks'][0]['stop_requested_at'], stop_confirmed=True)
  task['public']['state'] = state
  self.store.save(task)
  return task

 def reopen_service(self):
  self.store = Store(self.store.root)
  self.control = Control(self.store)
  self.service = Service({}, self.store, self.platform)

 def test_upgrade_recovers_final_results_from_legacy_terminal_snapshots(self):
  for state in ['stopped', 'failed', 'interrupted']:
   with self.subTest(state=state):
    task = self.legacy_terminal(state)
    self.assertNotIn('terminal_reconciled', task['internal'])
    self.complete(task)  # Old scheduler exited before copying this into SQLite.
    self.reopen_service()
    self.service.tick()
    self.assert_settled_completion(task)

 def test_upgrade_persists_confirmed_terminal_check_across_restarts(self):
  for state in ['stopped', 'failed', 'interrupted']:
   with self.subTest(state=state):
    task = self.legacy_terminal(state)
    if state == 'failed':
     self.status(task, 'failed', finished_at=1060)
    elif state == 'stopped':
     self.status(task)  # A killed runner left its last running snapshot.
    else:
     self.platform.resources = {'r':{'status':'closed'}}
    self.reopen_service()
    self.service.tick()
    saved = self.store.get(task['id'])
    self.assertEqual(saved['public']['state'], state)
    self.assertTrue(saved['internal'].get('terminal_reconciled'))
    self.reopen_service()
    with patch.object(self.store, 'save', wraps=self.store.save) as save, \
         patch('gpuqueue.service.read_json', side_effect=AssertionError('already reconciled read')):
     self.service.tick()
    save.assert_not_called()
    self.platform.request.assert_not_called()
    self.platform.submit_job.assert_not_called()

 def test_legacy_failure_without_exit_evidence_keeps_checking(self):
  task = self.legacy_terminal('failed')
  self.reopen_service()
  self.service.tick()
  self.assertFalse(self.store.get(task['id'])['internal'].get('terminal_reconciled'))
  self.complete(task)
  self.service.tick()
  self.assert_settled_completion(task)

if __name__=='__main__':unittest.main()
