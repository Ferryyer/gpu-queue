from concurrent.futures import ThreadPoolExecutor
import errno
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
from gpuqueue.core import Store,normalize,atomic_json,read_json,HOME,canonical
from gpuqueue.control import Control,ControlError
from gpuqueue.runner import execute
from gpuqueue import runner
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
 def test_concurrent_submission_reuses_existing_nonempty_snapshot(self):
  rename=Path.rename
  winner=[]
  def competing_rename(staging,folder):
   with patch.object(Path,'rename',rename):
    winner.append(self.store.submit(self.manifest)[0])
   self.assertTrue(any(folder.iterdir()))
   # Pin the Linux/macOS collision errno regardless of the test filesystem.
   raise OSError(errno.ENOTEMPTY,'Directory not empty',str(folder))
  with patch.object(Path,'rename',competing_rename):
   task,_=self.store.submit(self.manifest)
  self.assertEqual(task,winner[0])
  self.assertEqual(self.store.tasks(),[task])
  self.assertIsNone(task['internal']['approved_at'])
  folder=self.store.root/'tasks'/task['id']
  self.assertEqual((folder/'code/step.py').read_text(),self.script.read_text())
  self.assertEqual(list(folder.parent.glob('.prepare-*')),[])
 def test_submission_propagates_unexpected_rename_errors(self):
  with patch.object(Path,'rename',side_effect=PermissionError(errno.EACCES,'denied')):
   with self.assertRaises(PermissionError):self.store.submit(self.manifest)
  self.assertEqual(self.store.tasks(),[])
  self.assertEqual(list((self.store.root/'tasks').iterdir()),[])
 def test_snapshot_source_paths_require_code_placeholder(self):
  data=self.project/'data.txt';data.write_text('input data')
  home_script='{home}/'+str(self.script.resolve().relative_to(HOME))
  for argument in (str(self.script.resolve()),'{project}/step.py',home_script):
   with self.subTest(rejected=argument):
    self.manifest['steps'][0]['argv'][1]=argument
    with self.assertRaisesRegex(ValueError,'运行代码请引用'):normalize(self.manifest)
  for argument in ('{code}/step.py','{project}/data.txt'):
   with self.subTest(accepted=argument):
    self.manifest['steps'][0]['argv'][1]=argument
    doc,_=normalize(self.manifest)
    self.assertEqual(doc['steps'][0]['argv'][1],argument)
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

 def run_output_events(self, events, *, exit_code=0, steps=1, exit_at=None):
  # A deterministic child-output timeline: each event is (elapsed seconds, bytes).
  # The fake selector honors deadlines, including silent periods before an event.
  self.manifest['steps'] = [dict(name=f'step {i}', argv=['/usr/bin/python3', '-c', 'pass']) for i in range(steps)]
  folder = self.approve(self.task())
  clock = [0.0]
  chunk = [b'']
  writes = []
  timeouts = []
  process = Mock(pid=1234)
  process.wait.return_value = exit_code
  if exit_at is not None:
   def wait(timeout=None):
    if timeout is None or clock[0] + timeout >= exit_at:
     clock[0] = exit_at
     return exit_code
    clock[0] += timeout
    raise subprocess.TimeoutExpired('synthetic child', timeout)
   process.wait.side_effect = wait
  process.stdout.fileno.return_value = 123
  key = Mock(fileobj=process.stdout)

  def make_selector():
   pending = [(clock[0] + at, data) for at, data in events]
   registered = {123: key}
   selector = Mock()
   selector.get_map.side_effect = lambda: registered
   selector.unregister.side_effect = lambda _: registered.clear()

   def select(timeout):
    timeouts.append(timeout)
    at, data = pending[0]
    if at > clock[0] + timeout:
     clock[0] += timeout
     return []
    pending.pop(0)
    clock[0] = at
    chunk[0] = data
    return [(key, runner.selectors.EVENT_READ)]

   selector.select.side_effect = select
   return selector

  def save(path, status):
   runner_write(path, status)
   writes.append((clock[0], read_json(path)))

  runner_write = runner.write
  with patch.object(runner.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'GPU-test\n', '')), \
       patch.object(runner.subprocess, 'Popen', return_value=process), \
       patch.object(runner.selectors, 'DefaultSelector', side_effect=make_selector), \
       patch.object(runner.os, 'read', side_effect=lambda *_: chunk[0]) as reads, \
       patch.object(runner.time, 'monotonic', side_effect=lambda: clock[0]), \
       patch.object(runner.time, 'time', side_effect=lambda: 1000 + clock[0]), \
       patch.object(runner, 'write', side_effect=save):
   result = execute(folder)
  return result, folder, writes, timeouts, reads.call_count

 def test_runner_burst_output_does_not_fsync_status_per_chunk(self):
  events = [(i / 100, f'line {i}\n'.encode()) for i in range(1, 101)]
  result, folder, writes, _, reads = self.run_output_events(events + [(1.25, b'')])
  self.assertEqual(result, 0)
  self.assertEqual(reads, 101)
  self.assertEqual(len(writes), 5)
  self.assertEqual((folder/'run/step-0.log').read_bytes(), b''.join(data for _, data in events))
  self.assertEqual([s['state'] for _, s in writes], ['starting', 'running', 'running', 'running', 'completed'])
  self.assertEqual(writes[-2][1]['steps'][0]['state'], 'completed')
  self.assertEqual(writes[-1][0], 1.25)
  self.assertEqual(read_json(folder/'run/status.json'), writes[-1][1])

 def test_runner_continuous_output_keeps_ten_second_heartbeats(self):
  events = [(i / 4, b'progress\r') for i in range(1, 101)]
  result, _, writes, _, _ = self.run_output_events(events + [(25.25, b'')])
  self.assertEqual(result, 0)
  self.assertEqual([at for at, _ in writes[3:-2]], [10, 20])
  self.assertEqual([s['updated_at'] for _, s in writes[3:-2]], [1010, 1020])

 def test_runner_real_child_burst_preserves_all_output_with_few_status_writes(self):
  self.manifest['steps'] = [dict(name='noisy child', argv=['/usr/bin/python3', '-c',
      "import sys; sys.stdout.buffer.write(b'line\\n' * 200000)"])]
  folder = self.approve(self.task())
  with patch.object(runner.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'GPU-test\n', '')), \
       patch.object(runner.time, 'monotonic', return_value=0), \
       patch.object(runner.os, 'read', wraps=os.read) as reads, \
       patch.object(runner, 'write', wraps=runner.write) as writes:
   self.assertEqual(execute(folder), 0)
  self.assertGreater(reads.call_count, 15)
  self.assertEqual(writes.call_count, 5)
  self.assertEqual((folder/'run/step-0.log').read_bytes(), b'line\n' * 200000)
  self.assertEqual(read_json(folder/'run/status.json')['state'], 'completed')

 def test_runner_silent_child_keeps_ten_second_heartbeats(self):
  result, _, writes, timeouts, _ = self.run_output_events([(30.5, b'')])
  self.assertEqual(result, 0)
  self.assertEqual(timeouts, [10, 10, 10, 10])
  self.assertEqual([at for at, _ in writes[3:-2]], [10, 20, 30])

 def test_runner_output_before_silence_does_not_postpone_heartbeat(self):
  result, _, writes, timeouts, _ = self.run_output_events([(9.75, b'progress'), (20.5, b'')])
  self.assertEqual(result, 0)
  self.assertEqual(timeouts, [10, 0.25, 10, 10])
  self.assertEqual([at for at, _ in writes[3:-2]], [10, 20])

 def test_runner_early_eof_keeps_heartbeat_until_child_exits(self):
  result, folder, writes, _, _ = self.run_output_events([(9, b'')], exit_at=185)
  self.assertEqual(result, 0)
  self.assertEqual([at for at, _ in writes[3:-2]], list(range(10, 181, 10)))
  # A scheduler read at 182 seconds must see a live step, not a stale heartbeat.
  observed_at, observed = [entry for entry in writes if entry[0] <= 182][-1]
  self.assertLessEqual(182 - observed_at, 10)
  self.assertEqual(observed['state'], 'running')
  self.assertEqual(observed['updated_at'], 1180)
  self.assertEqual(writes[-1][0], 185)
  final = read_json(folder/'run/status.json')
  self.assertEqual(final['state'], 'completed')
  task = self.store.get(folder.name)
  task['internal'].update(request_uuid='synthetic-resource', job_uuid='synthetic-job')
  platform = Mock(resources={})
  platform.job_folder.return_value = self.root/'jobs'
  service = Service({}, self.store, platform)
  atomic_json(folder/'run/status.json', observed)
  with patch.object(runner.time, 'time', return_value=1182):
   service.refresh_task(task)
  self.assertEqual(task['public']['state'], 'running')
  self.assertFalse(task['public'].get('failureReason'))
  atomic_json(folder/'run/status.json', final)
  with patch.object(runner.time, 'time', return_value=1185):
   service.refresh_task(task)
  self.assertEqual(task['public']['state'], 'completed')
  self.assertFalse(task['public'].get('failureReason'))

 def test_runner_early_eof_failure_is_written_at_child_exit(self):
  result, folder, writes, _, _ = self.run_output_events([(9, b'')], exit_at=22, exit_code=7)
  self.assertEqual(result, 1)
  self.assertEqual([at for at, _ in writes[3:-1]], [10, 20])
  self.assertEqual(writes[-1][0], 22)
  status = read_json(folder/'run/status.json')
  self.assertEqual(status['state'], 'failed')
  self.assertEqual(status['steps'][0]['exit_code'], 7)

 def test_runner_failure_is_written_before_heartbeat_deadline(self):
  result, folder, writes, _, _ = self.run_output_events([(0.25, b'error\n'), (0.5, b'')], exit_code=7)
  self.assertEqual(result, 1)
  self.assertEqual(len(writes), 4)
  self.assertEqual(writes[-1][0], 0.5)
  status = read_json(folder/'run/status.json')
  self.assertEqual(status['state'], 'failed')
  self.assertEqual(status['steps'][0]['state'], 'failed')
  self.assertEqual(status['steps'][0]['exit_code'], 7)

 def test_runner_step_boundaries_are_written_before_heartbeat_deadline(self):
  result, _, writes, _, _ = self.run_output_events([(0.25, b'output\n'), (0.5, b'')], steps=2)
  self.assertEqual(result, 0)
  self.assertEqual([at for at, _ in writes], [0, 0, 0, 0.5, 0.5, 0.5, 1, 1])
  self.assertEqual(writes[3][1]['steps'][0]['state'], 'completed')
  self.assertEqual(writes[4][1]['stage'], 1)
  self.assertEqual(writes[4][1]['steps'][1]['state'], 'running')
  self.assertEqual(writes[6][1]['steps'][1]['state'], 'completed')
  self.assertEqual(writes[7][1]['state'], 'completed')

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

 def execution_service(self, state='running', age=181, job_state='finished'):
  self.manifest['submission_key']=f'{state}-{age}-{job_state}'
  task=self.task();folder=self.store.root/'tasks'/task['id']
  request='11111111-1111-4111-8111-111111111111';job='22222222-2222-4222-8222-222222222222'
  task['internal'].update(approved_at='browser',dispatch='submitted',request_uuid=request,job_uuid=job,dispatched_at=900)
  task['public']['state']='execution_unknown';self.store.save(task)
  status={'state':state,'started_at':900,'updated_at':1000-age,'stage':0,'steps':[{'name':'first','state':state}]}
  if state in ['completed','failed']:status['finished_at']=950
  atomic_json(folder/'run/status.json',status)
  (folder/'run/step-0.log').write_text('existing step log\n')
  (folder/'outputs/one.json').write_text('{"checkpoint":true}')
  adapter=Markflow(self.store,{'home':str(self.root)})
  adapter.resources={request:{'id':request,'status':'online','type':'H卡离线','telemetry':{'at':1000,'gpus':[{'uuid':'GPU-test','total_mb':81920,'used_mb':1}],'apps':[]}}}
  job_file=adapter.job_folder(request)/job/'status.json'
  if job_state is not None:atomic_json(job_file,{'state':job_state})
  else:job_file.unlink(missing_ok=True)
  adapter.refresh=Mock();adapter.request=Mock();adapter.submit_job=Mock()
  return Service({},self.store,adapter),task,folder

 def test_stale_execution_with_finished_job_is_interrupted_and_preserves_files(self):
  for state in ['starting','running']:
   for job_state in ['finished','failed']:
    with self.subTest(state=state,job_state=job_state):
     service,task,folder=self.execution_service(state=state,job_state=job_state)
     before={p:p.read_bytes() for p in [folder/'run/status.json',folder/'run/step-0.log',folder/'outputs/one.json']}
     with patch('gpuqueue.service.time.time',return_value=1000):
      service.refresh_task(task)
      service.refresh_task(self.store.get(task['id']))
     saved=self.store.get(task['id'])
     self.assertEqual(saved['public']['state'],'interrupted')
     self.assertIn('执行进程已退出',saved['public']['failureReason'])
     self.assertIn('未自动重跑',saved['public']['failureReason'])
     self.assertEqual(saved['public']['step_records'][0]['log'],'existing step log\n')
     self.assertEqual(before,{p:p.read_bytes() for p in before})
     self.assertEqual(saved['internal']['job_uuid'],task['internal']['job_uuid'])
     service.platform.request.assert_not_called();service.platform.submit_job.assert_not_called()

 def test_interrupted_execution_no_longer_blocks_next_approved_task(self):
  service,task,folder=self.execution_service()
  self.manifest['submission_key']='next'
  pending=self.task();pending['internal'].update(approved_at='browser',position=1);pending['public']['state']='queued';self.store.save(pending)
  service.dispatch=Mock()
  with patch('gpuqueue.service.time.time',return_value=1000):service.tick()
  self.assertEqual(self.store.get(task['id'])['public']['state'],'interrupted')
  service.dispatch.assert_called_once()
  self.assertEqual(service.dispatch.call_args.args[0]['id'],pending['id'])
  self.assertEqual(service.dispatch.call_args.args[1][1],['GPU-test'])
  service.platform.request.assert_not_called();service.platform.submit_job.assert_not_called()

 def test_unreadable_job_receipt_with_stale_heartbeat_remains_unknown(self):
  for error in [PermissionError('fixture denied'),json.JSONDecodeError('fixture incomplete','{',1)]:
   with self.subTest(error=type(error).__name__):
    service,task,folder=self.execution_service()
    job_file=service.platform.job_folder(task['internal']['request_uuid'])/task['internal']['job_uuid']/'status.json'
    def read(path,default=None):
     if path==job_file:raise error
     return read_json(path,default)
    with patch('gpuqueue.service.read_json',side_effect=read),patch('gpuqueue.service.time.time',return_value=1000):service.refresh_task(task)
    self.assertEqual(task['public']['state'],'execution_unknown')
    service.platform.request.assert_not_called();service.platform.submit_job.assert_not_called()

 def test_stale_execution_with_live_or_missing_job_remains_unknown(self):
  for job_state in ['starting','running',None]:
   with self.subTest(job_state=job_state):
    service,task,folder=self.execution_service(job_state=job_state)
    with patch('gpuqueue.service.time.time',return_value=1000):service.refresh_task(task)
    self.assertEqual(task['public']['state'],'execution_unknown')
    pending=self.task()
    self.assertIsNone(service.platform.select(pending,[task])[0])
    service.platform.request.assert_not_called();service.platform.submit_job.assert_not_called()

 def test_fresh_heartbeat_keeps_runner_state_even_if_job_has_ended(self):
  for state in ['starting','running']:
   for age in [0,180]:
    with self.subTest(state=state,age=age):
     service,task,folder=self.execution_service(state=state,age=age)
     with patch('gpuqueue.service.time.time',return_value=1000):service.refresh_task(task)
     self.assertEqual(task['public']['state'],state)

 def test_terminal_runner_states_are_preserved_with_stale_heartbeat(self):
  for state in ['completed','failed']:
   for job_state in ['finished','failed']:
    with self.subTest(state=state,job_state=job_state):
     service,task,folder=self.execution_service(state=state,job_state=job_state)
     with patch('gpuqueue.service.time.time',return_value=1000):service.refresh_task(task)
     self.assertEqual(task['public']['state'],state)
     self.assertTrue(task['internal']['finished_recorded'])

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

class BlockedStopTests(unittest.TestCase):
    """Exercise real queue selection with private records and a mock platform."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root/'queue')
        self.control = Control(self.store)
        self.task = self.add_task(1)
        self.following = self.add_task(2)
        self.folder = self.store.root/'tasks'/self.task['id']
        self.argv = ['/usr/bin/python3', '-I', str(self.folder/'run/stop-control.py'), 'supervise', str(self.folder)]
        self.platform = Markflow(self.store, {'home': str(self.root)})
        self.platform.refresh = Mock()
        self.platform.request = Mock(return_value=None)
        self.platform.submit_job = Mock(return_value='control-job')
        self.platform.begin_task_sampling = Mock()
        self.platform.select = Mock(wraps=self.platform.select)
        self.service = Service({}, self.store, self.platform)

    def tearDown(self):
        self.temp.cleanup()

    def add_task(self, index):
        task_id, digest = 'GQ-'+str(index).zfill(16), str(index)*64
        public = {'id': task_id, 'name': 'isolated fixture', 'state': 'ready', 'events': []}
        doc = {'project': str(self.root), 'resources': {'type': 'H卡离线', 'gpus': 1, 'memory_gb': 2}}
        with self.store.connect() as db:
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',
                       (task_id, digest, canonical(doc), canonical(public), '{}'))
        (self.store.root/'tasks'/task_id/'run').mkdir(parents=True)
        return self.store.get(task_id)

    def blocked(self, *, claim=True, dispatch='unknown', marker=True):
        state = self.control.start(self.task['id'], self.task['digest'])
        if claim:
            self.control.claim(self.task['id'], self.task['digest'], state['revision'])
        task = self.store.get(self.task['id'])
        task['public'].update(state='blocked', failureReason='原计算回执待核查')
        task['internal'].update(request_uuid='original', argv=self.argv)
        if dispatch:
            task['internal']['dispatch'] = dispatch
        self.store.save(task)
        if marker:
            atomic_json(self.folder/'run/dispatch.json', {'task': task['id'], 'digest': task['digest'],
                        'request': 'original', 'argv': self.argv})
        self.control.start(self.following['id'], self.following['digest'])

    def stop(self):
        state = self.control.stop(self.task['id'], self.task['digest'])
        return next(t for t in state['tasks'] if t['id'] == self.task['id'])

    def receipt(self, job='compute-job', argv=None, request='original'):
        atomic_json(self.platform.job_folder(request)/(job+'.json'), {'argv': argv or self.argv})

    def proof(self, **changes):
        task = self.store.get(self.task['id'])
        shown = next(t for t in self.control.state()['tasks'] if t['id'] == task['id'])
        value = {'task': task['id'], 'digest': task['digest'], 'stop_at': shown['stop_requested_at'],
                 'uid': os.getuid(), 'request': 'original', 'job': 'compute-job', 'mode': 'supervisor', 'state': 'stopped'}
        atomic_json(self.folder/'run/stop-result.json', {**value, **changes})

    def restart(self):
        self.store = Store(self.store.root)
        self.control = Control(self.store)
        self.service = Service({}, self.store, self.platform)

    def idle_resource(self, request='available'):
        self.platform.resources[request] = {'id': request, 'status': 'online', 'type': 'H卡离线',
            'telemetry': {'at': time.time(), 'gpus': [{'uuid': 'GPU-fixture', 'total_mb': 81920, 'used_mb': 1}], 'apps': []}}

    def assert_waiting(self):
        task = self.store.get(self.task['id'])
        self.assertEqual(task['public']['state'], 'stopping')
        self.assertFalse(task['internal'].get('stop_confirmed'))
        shown = next(t for t in self.control.state()['tasks'] if t['id'] == task['id'])
        self.assertEqual(shown['state'], 'stopping')
        self.assertIsNone(shown['stopped_at'])
        with self.assertRaises(ControlError): self.control.delete(task['id'], task['digest'])
        self.platform.request.assert_not_called()
        self.assertFalse(self.store.get(self.following['id'])['internal'].get('dispatch'))
        selection, reason = self.platform.select(self.following, [task])
        self.assertIsNone(selection)
        self.assertIn('待核查', reason)

    def assert_next_dispatched(self):
        following = self.store.get(self.following['id'])
        self.assertEqual(following['internal']['dispatch'], 'submitted')
        calls = self.platform.submit_job.call_args_list
        self.assertEqual(calls[-1].args[0], 'available')
        self.assertIn(str(self.store.root/'tasks'/following['id']), calls[-1].args[1])
        self.platform.request.assert_not_called()

    def crash_after_selecting_reused_gpu(self):
        self.control.start(self.task['id'], self.task['digest'])
        self.service.sync()
        task = self.store.get(self.task['id'])
        task['internal']['request_uuid'] = 'requested-A'
        self.store.save(task)
        # The real dispatch writes B's marker after claiming, before saving the
        # execution identity in SQLite. No compute submit has happened yet.
        with patch.object(self.store, 'save', side_effect=RuntimeError('fixture crash')):
            with self.assertRaisesRegex(RuntimeError, 'fixture crash'):
                self.service.dispatch(task, ({'id': 'reused-B'}, ['GPU-fixture']))
        self.platform.submit_job.assert_not_called()
        saved = self.store.get(task['id'])
        self.assertEqual(saved['internal']['request_uuid'], 'requested-A')
        self.assertFalse(saved['internal'].get('argv'))
        self.assertFalse(saved['internal'].get('dispatch'))
        marker = (self.folder/'run/dispatch.json').read_bytes()
        self.control.start(self.following['id'], self.following['digest'])
        self.restart()
        self.service.sync()
        self.stop()
        return marker

    def test_reused_allocation_marker_survives_crash_with_only_application_uuid_saved(self):
        marker = self.crash_after_selecting_reused_gpu()
        self.platform.resources['reused-B'] = {'id': 'reused-B', 'status': 'closed'}
        self.idle_resource()
        self.service.tick()
        task = self.store.get(self.task['id'])
        self.assertTrue(task['internal'].get('stop_confirmed'))
        self.assertEqual(task['internal']['request_uuid'], 'reused-B')
        self.assertEqual(task['internal']['dispatch'], 'unknown')
        self.assertEqual((self.folder/'run/dispatch.json').read_bytes(), marker)
        self.assert_next_dispatched()
        self.control.delete(task['id'], task['digest'])
        self.restart()
        self.service.tick()
        self.assertNotIn(task['id'], [t['id'] for t in self.control.state()['tasks']])
        self.assertEqual(self.platform.submit_job.call_count, 1)

    def test_reused_allocation_marker_can_reconcile_unique_receipt_and_stop_proof(self):
        self.crash_after_selecting_reused_gpu()
        self.receipt(request='reused-B')
        self.proof(request='reused-B', job=None)
        self.idle_resource()
        self.service.tick()
        task = self.store.get(self.task['id'])
        self.assertTrue(task['internal'].get('stop_confirmed'))
        self.assertEqual(task['internal']['request_uuid'], 'reused-B')
        self.assertEqual(task['internal']['job_uuid'], 'compute-job')
        self.assert_next_dispatched()
        self.assertEqual(self.platform.submit_job.call_count, 1)

    def test_saved_dispatch_identity_still_rejects_conflicting_allocation_marker(self):
        self.blocked()
        self.stop()
        marker = read_json(self.folder/'run/dispatch.json')
        atomic_json(self.folder/'run/dispatch.json', {**marker, 'request': 'other'})
        self.platform.resources['original'] = {'id': 'original', 'status': 'closed'}
        self.platform.resources['other'] = {'id': 'other', 'status': 'closed'}
        for evidence in [{'dispatch': 'submitting'}, {'dispatch': 'submitted'},
                         {'dispatch': 'unknown', 'dispatched_at': time.time()},
                         {'dispatch': 'unknown', 'job_uuid': 'compute-job'}]:
            with self.subTest(evidence=evidence):
                task = self.store.get(self.task['id'])
                task['internal'] = {'request_uuid': 'original', **evidence}
                self.store.save(task)
                self.service.tick()
                self.assert_waiting()
        self.platform.submit_job.assert_not_called()

    def test_closed_confirmation_later_imports_verified_completion_without_reoccupying_queue(self):
        self.blocked()
        self.stop()
        atomic_json(self.folder/'run/status.json', {'state': 'completed', 'stage': 1,
            'started_at': time.time()-10, 'updated_at': time.time(), 'finished_at': time.time(),
            'steps': [{'state': 'completed', 'outputs': [{'name': 'result.txt', 'size': 5}]}]})
        (self.folder/'run/step-0.log').write_text('saved final log')
        output = self.folder/'outputs/result.txt'
        output.parent.mkdir(); output.write_text('saved')
        self.platform.resources['original'] = {'id': 'original', 'status': 'closed'}
        self.idle_resource()
        self.service.tick()
        self.assert_next_dispatched()
        task = self.store.get(self.task['id'])
        self.assertEqual(task['public']['state'], 'stopped')  # Receipt still missing.
        dispatch = {k: task['internal'].get(k) for k in ['request_uuid', 'job_uuid', 'dispatch', 'argv']}
        marker = (self.folder/'run/dispatch.json').read_bytes()
        stopped_at = next(t for t in self.control.state()['tasks'] if t['id']==task['id'])['stopped_at']
        self.restart()
        self.receipt()
        self.service.tick()
        for _ in range(2):
            self.restart()
            self.service.tick()
            task = self.store.get(self.task['id'])
            self.assertEqual(task['public']['state'], 'completed')
            self.assertTrue(task['internal']['stop_confirmed'])
            self.assertEqual({k: task['internal'].get(k) for k in dispatch}, dispatch)
            self.assertEqual(task['public']['step_records'][0]['outputs'][0]['name'], 'result.txt')
            self.assertEqual(task['public']['step_records'][0]['log'], 'saved final log')
            shown = next(t for t in self.control.state()['tasks'] if t['id']==task['id'])
            self.assertEqual(shown['state'], 'completed')
            self.assertEqual(shown['stopped_at'], stopped_at)
        self.assertEqual(output.read_text(), 'saved')
        self.assertEqual((self.folder/'run/dispatch.json').read_bytes(), marker)
        self.assertEqual(self.platform.submit_job.call_count, 1)
        self.platform.request.assert_not_called()
        with self.assertRaises(ControlError): self.control.delete(task['id'], 'stale')
        self.control.delete(task['id'], task['digest'])
        self.restart()
        self.service.tick()
        self.assertNotIn(task['id'], [t['id'] for t in self.control.state()['tasks']])
        self.assertEqual(output.read_text(), 'saved')
        self.assertEqual((self.folder/'run/dispatch.json').read_bytes(), marker)
        self.assertEqual(self.store.get(task['id'])['internal']['dispatch'], 'unknown')

    def test_confirmed_late_completion_remains_eligible_for_existing_cleanup_filter(self):
        self.blocked()
        self.stop()
        self.platform.resources['original'] = {'id': 'original', 'status': 'closed'}
        self.idle_resource()
        self.service.tick()
        state = self.control.state()
        with self.assertRaises(ControlError): self.control.cleanup([self.task['id']], state['revision'])
        self.receipt()
        atomic_json(self.folder/'run/status.json', {'state': 'completed', 'stage': 1,
            'started_at': time.time()-10, 'steps': [{'state': 'completed', 'outputs': ['saved']} ]})
        self.service.tick()
        state = self.control.state()
        self.assertEqual(next(t for t in state['tasks'] if t['id']==self.task['id'])['state'], 'completed')
        self.control.cleanup([self.task['id']], state['revision'])
        self.restart()
        self.service.tick()
        self.assertNotIn(self.task['id'], [t['id'] for t in self.control.state()['tasks']])
        task = self.store.get(self.task['id'])
        self.assertEqual(task['public']['step_records'][0]['outputs'], ['saved'])
        self.assertEqual(task['internal']['dispatch'], 'unknown')

    def test_invalid_late_job_status_does_not_block_successor_and_can_recover(self):
        self.blocked()
        self.stop()
        self.platform.resources['original'] = {'id': 'original', 'status': 'closed'}
        self.idle_resource()
        self.service.tick()
        # The first successor finished before the original receipt arrived.
        following = self.store.get(self.following['id'])
        following['public']['state'] = 'completed'
        self.store.save(following)
        next_task = self.add_task(3)
        self.control.start(next_task['id'], next_task['digest'])
        original = self.store.get(self.task['id'])
        original_internal = dict(original['internal'])
        marker = (self.folder/'run/dispatch.json').read_bytes()
        stopped_at = next(t for t in self.control.state()['tasks'] if t['id']==original['id'])['stopped_at']
        self.receipt()
        status_path = self.platform.job_folder('original')/'compute-job/status.json'
        status_path.parent.mkdir(); status_path.write_text('{invalid late status')
        atomic_json(self.folder/'run/status.json', {'state': 'completed', 'stage': 1,
            'started_at': time.time()-10, 'steps': [{'state': 'completed', 'outputs': ['kept-result']}]})
        (self.folder/'run/step-0.log').write_text('kept log')
        for _ in range(2):
            self.restart()
            self.service.tick()
            task = self.store.get(original['id'])
            self.assertEqual(task['public']['state'], 'stopped')
            self.assertEqual(task['internal'], original_internal)
            self.assertIn('迟到结果读取失败', task['public']['result_refresh_error'])
            self.assertEqual(sum('迟到结果读取失败' in event for event in task['public']['events']), 1)
            self.assertEqual(task['public'].get('step_records', []), original['public'].get('step_records', []))
            self.assertEqual(next(t for t in self.control.state()['tasks'] if t['id']==task['id'])['stopped_at'], stopped_at)
        self.assertEqual(self.store.get(next_task['id'])['internal']['dispatch'], 'submitted')
        self.assertEqual(self.platform.submit_job.call_count, 2)  # Successors only.
        self.platform.request.assert_not_called()
        self.assertEqual((self.folder/'run/dispatch.json').read_bytes(), marker)
        atomic_json(status_path, {'state': 'finished'})
        self.service.tick()
        recovered = self.store.get(original['id'])
        self.assertEqual(recovered['public']['state'], 'completed')
        self.assertNotIn('result_refresh_error', recovered['public'])
        self.assertEqual(recovered['public']['step_records'][0]['outputs'], ['kept-result'])
        self.assertEqual(recovered['public']['step_records'][0]['log'], 'kept log')
        for key in ['dispatch', 'job_uuid', 'request_uuid', 'argv', 'stop_confirmed']:
            self.assertEqual(recovered['internal'].get(key), original_internal.get(key))
        self.assertEqual(self.platform.submit_job.call_count, 2)

    def test_confirmed_result_read_errors_preserve_snapshot_and_retry(self):
        self.blocked()
        self.stop()
        self.platform.resources['original'] = {'id': 'original', 'status': 'closed'}
        self.idle_resource()
        self.service.tick()
        self.receipt()
        task = self.store.get(self.task['id'])
        task['public']['step_records'] = [{'state': 'completed', 'outputs': ['earlier-result']}]
        self.store.save(task)
        path = self.folder/'run/status.json'
        for payload in ['{broken runner status', '{"state":"completed","steps":42}', '{"state":"completed","started_at":"invalid"}']:
            with self.subTest(payload=payload):
                path.write_text(payload)
                self.restart()
                self.service.tick()
                saved = self.store.get(task['id'])
                self.assertEqual(saved['public']['state'], 'stopped')
                self.assertEqual(saved['public']['step_records'], task['public']['step_records'])
                self.assertIn('迟到结果读取失败', saved['public']['result_refresh_error'])
        path.unlink()
        def read_with_denied_result(file, *args):
            if Path(file) == path:
                raise PermissionError('fixture read denied')
            return read_json(file, *args)
        with patch('gpuqueue.service.read_json', side_effect=read_with_denied_result):
            # Isolate a read failure, leaving database persistence available.
            self.service.refresh_task(self.store.get(task['id']))
        self.assertEqual(self.store.get(task['id'])['public']['state'], 'stopped')
        self.assertIn('PermissionError', self.store.get(task['id'])['public']['result_refresh_error'])
        self.platform.request.assert_not_called()
        self.assertEqual(self.platform.submit_job.call_count, 1)

    def test_persisted_confirmation_survives_bad_late_status_after_snapshot_crash(self):
        self.blocked()
        self.stop()
        self.service.sync()
        task = self.store.get(self.task['id'])
        self.platform.resources['original'] = {'id': 'original', 'status': 'closed'}
        with patch.object(self.store, 'save', side_effect=RuntimeError('fixture snapshot crash')):
            with self.assertRaisesRegex(RuntimeError, 'fixture snapshot crash'):
                self.service.process_stop(task)
        self.assertFalse(self.store.get(task['id'])['internal'].get('stop_confirmed'))
        self.receipt()
        path = self.platform.job_folder('original')/'compute-job/status.json'
        path.parent.mkdir(); path.write_text('{invalid late status')
        self.idle_resource()
        self.restart()
        self.service.tick()
        saved = self.store.get(task['id'])
        self.assertTrue(saved['internal']['stop_confirmed'])
        self.assertEqual(saved['public']['state'], 'stopped')
        self.assertIn('JSONDecodeError', saved['public']['result_refresh_error'])
        self.assertEqual(saved['internal']['dispatch'], 'unknown')
        self.assertNotIn('job_uuid', saved['internal'])
        self.assert_next_dispatched()
        self.assertEqual(self.platform.submit_job.call_count, 1)

    def test_unconfirmed_invalid_job_status_still_fails_closed(self):
        self.blocked()
        self.stop()
        self.receipt()
        path = self.platform.job_folder('original')/'compute-job/status.json'
        path.parent.mkdir(); path.write_text('{broken status')
        with self.assertRaises(ValueError): self.service.tick()
        self.platform.submit_job.assert_not_called()
        self.platform.request.assert_not_called()
        with self.assertRaises(ControlError): self.control.delete(self.task['id'], self.task['digest'])

    def test_late_live_receipt_cannot_undo_confirmed_stop(self):
        self.blocked()
        self.stop()
        self.platform.resources['original'] = {'id': 'original', 'status': 'closed'}
        self.idle_resource()
        self.service.tick()
        self.receipt()
        atomic_json(self.folder/'run/status.json', {'state': 'running', 'stage': 0,
            'started_at': time.time()-10, 'updated_at': time.time(), 'steps': [{'state': 'running'}]})
        self.restart()
        self.service.tick()
        task = self.store.get(self.task['id'])
        self.assertEqual(task['public']['state'], 'stopped')
        self.assertEqual(task['public']['step_records'][0]['state'], 'stopped')
        self.assertTrue(task['internal']['stop_confirmed'])
        self.assertEqual(task['internal']['dispatch'], 'unknown')
        self.assertNotIn('job_uuid', task['internal'])
        self.assertEqual(self.platform.submit_job.call_count, 1)

    def test_stop_snapshot_replaces_stale_dispatch_phase_before_scheduler_sync(self):
        self.blocked()
        task = self.store.get(self.task['id'])
        task['public']['phase'] = '等待 GPU 执行入口领取任务'
        self.store.save(task)
        shown = self.stop()
        self.assertEqual(shown['state'], 'stopping')
        self.assertIn('停止状态待核查', shown['phase'])
        self.assertIn('原计算回执待核查', shown['phase'])
        self.assertNotIn('等待 GPU 执行入口', shown['phase'])
        self.assertFalse(self.store.get(task['id'])['internal'].get('stop_requested_at'))
        self.assertEqual(self.stop()['phase'], shown['phase'])

    def test_blocked_stop_is_version_bound_idempotent_across_restart(self):
        self.blocked()
        with self.assertRaises(ControlError): self.control.stop(self.task['id'], 'stale-digest')
        first = self.stop()
        self.assertEqual(first['state'], 'stopping')
        self.assertIn('待核查', first['failureReason'])
        self.service.tick()
        self.restart()
        self.assertEqual(self.stop()['stop_requested_at'], first['stop_requested_at'])
        self.service.tick()
        self.assert_waiting()
        self.platform.submit_job.assert_not_called()
        self.assertEqual(read_json(self.folder/'run/stop.json')['at'], first['stop_requested_at'])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM queue_audit WHERE action LIKE 'browser_stop:%'").fetchone()[0], 1)

    def test_missing_and_conflicting_receipts_keep_queue_and_delete_blocked(self):
        self.blocked()
        self.stop()
        self.idle_resource()
        for jobs in [(), ('one', 'two')]:
            for job in jobs: self.receipt(job)
            self.service.tick()
            self.assert_waiting()
            self.assertIn('待核查', next(t for t in self.control.state()['tasks'] if t['id']==self.task['id'])['phase'])
        self.platform.submit_job.assert_not_called()

    def test_wrong_version_or_allocation_marker_cannot_reconcile_or_confirm_closed(self):
        self.blocked()
        self.stop()
        self.receipt()
        self.platform.resources['original'] = {'id': 'original', 'status': 'closed'}
        marker = read_json(self.folder/'run/dispatch.json')
        for changes in [{'digest': 'old'}, {'task': self.following['id']}, {'request': 'other'}, {'argv': ['other-runner']}]:
            with self.subTest(changes=changes):
                atomic_json(self.folder/'run/dispatch.json', {**marker, **changes})
                self.service.tick()
                self.assert_waiting()
        self.platform.submit_job.assert_not_called()

    def test_claimed_history_without_dispatch_is_never_assumed_unexecuted(self):
        self.blocked(dispatch=None, marker=False)
        task = self.store.get(self.task['id']); task['internal'] = {}; self.store.save(task)
        self.stop()
        # Null identities must not make a fabricated proof match a missing job.
        self.service.sync()
        self.proof(request=None, job=None)
        self.service.tick()
        self.restart()
        self.service.tick()
        self.assert_waiting()
        self.platform.submit_job.assert_not_called()

    def test_blocked_execution_without_claim_record_still_requires_confirmation(self):
        self.blocked(claim=False, dispatch=None, marker=False)
        task = self.store.get(self.task['id']); task['internal'] = {}; self.store.save(task)
        self.assertEqual(self.stop()['state'], 'stopping')
        self.service.tick()
        self.assert_waiting()
        self.platform.submit_job.assert_not_called()

    def test_old_resource_query_timeout_keeps_both_tasks_unsubmitted(self):
        self.blocked()
        self.stop()
        self.platform.resources['original'] = {'id': 'original', 'status': 'unknown',
            'probe_timeout': {'at': 'fixture'}, 'error': 'GPU 检查超时；旧实例是否回收尚未确认'}
        self.service.tick()
        self.assert_waiting()
        self.platform.submit_job.assert_not_called()

    def test_invalid_and_unverified_proofs_never_confirm_stop(self):
        self.blocked()
        self.stop()
        self.receipt()
        self.service.tick()
        self.idle_resource()
        cases = [{'digest': 'old'}, {'task': self.following['id']}, {'stop_at': 'old'},
                 {'uid': os.getuid()+1}, {'request': 'other'}, {'job': 'other'},
                 {'state': 'unverified', 'error': 'process identity not verified'}]
        for changes in cases:
            with self.subTest(changes=changes):
                self.proof(**changes)
                self.service.tick()
                self.assert_waiting()
        self.assertIn('process identity not verified', self.store.get(self.task['id'])['public']['phase'])
        self.platform.submit_job.assert_not_called()

    def test_malformed_receipts_and_proofs_stay_pending(self):
        self.blocked()
        self.stop()
        path = self.platform.job_folder('original')/'broken.json'
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text('{broken')
        self.proof()
        self.service.tick()
        self.assert_waiting()
        path.unlink()
        self.receipt()
        (self.folder/'run/stop-result.json').write_text('{broken')
        self.service.tick()
        self.assert_waiting()
        self.platform.submit_job.assert_not_called()

    def test_late_unique_receipt_and_matching_supervisor_proof_resume_queue(self):
        self.blocked()
        self.stop()
        self.service.tick()
        # The supervisor may exit before the submitting service writes job UUID.
        self.proof(job=None)
        self.service.tick()
        self.assert_waiting()
        self.receipt()
        self.idle_resource()
        self.service.tick()
        task = self.store.get(self.task['id'])
        self.assertEqual(task['public']['state'], 'stopped')
        self.assertTrue(task['internal']['stop_confirmed'])
        self.assertEqual(task['internal']['job_uuid'], 'compute-job')
        self.assert_next_dispatched()
        self.assertEqual(self.platform.submit_job.call_count, 1)  # Only the next compute.

    def test_closed_allocation_confirms_without_unique_receipt_and_survives_late_results(self):
        self.blocked()
        self.stop()
        self.service.tick()
        marker = (self.folder/'run/dispatch.json').read_bytes()
        (self.folder/'run/stop-result.json').write_text('{invalid proof')
        self.platform.resources['original'] = {'id': 'original', 'status': 'closed'}
        self.idle_resource()
        self.service.tick()
        self.assert_next_dispatched()
        for _ in range(2):
            self.restart()
            self.receipt()
            self.receipt('second-late-receipt')
            self.service.tick()
            task = self.store.get(self.task['id'])
            self.assertEqual(task['public']['state'], 'stopped')
            self.assertEqual(task['internal']['dispatch'], 'unknown')
            self.assertNotIn('job_uuid', task['internal'])
        self.assertEqual((self.folder/'run/dispatch.json').read_bytes(), marker)
        self.assertEqual(self.platform.submit_job.call_count, 1)

    def test_bound_dispatch_marker_recovers_original_allocation_for_closed_confirmation(self):
        self.blocked()
        task = self.store.get(self.task['id']); task['internal'] = {'dispatch': 'unknown'}; self.store.save(task)
        self.stop()
        self.platform.resources['original'] = {'id': 'original', 'status': 'closed'}
        self.idle_resource()
        self.service.tick()
        self.assertTrue(self.store.get(self.task['id'])['internal']['stop_confirmed'])
        self.assertNotIn('failureReason', self.store.get(self.task['id'])['public'])
        self.assert_next_dispatched()

    def test_stop_command_unknown_receipt_is_not_resent_across_restart(self):
        self.blocked()
        self.stop()
        self.argv = ['/usr/bin/python3', '-I', str(self.folder/'runner.py'), str(self.folder)]
        task = self.store.get(self.task['id']); task['internal']['argv'] = self.argv; self.store.save(task)
        marker = read_json(self.folder/'run/dispatch.json'); marker['argv'] = self.argv
        atomic_json(self.folder/'run/dispatch.json', marker)
        self.receipt()
        self.platform.submit_job.side_effect = RuntimeError('mock submit timeout')
        self.service.cycle()
        self.assertEqual(self.platform.submit_job.call_count, 1)
        task = self.store.get(self.task['id'])
        self.assertEqual(task['internal']['stop_dispatch'], 'submitting')
        self.restart()
        self.service.tick()
        self.assert_waiting()
        self.assertEqual(self.platform.submit_job.call_count, 1)
        self.receipt('late-control', task['internal']['stop_argv'])
        self.service.tick()
        self.assertEqual(self.store.get(task['id'])['internal']['stop_job_uuid'], 'late-control')
        self.proof(mode='legacy')
        self.service.tick()
        self.assertTrue(self.store.get(task['id'])['internal']['stop_confirmed'])
        self.assertEqual(self.platform.submit_job.call_count, 1)

    def test_confirmation_crash_before_task_save_is_recovered_from_controls(self):
        self.blocked()
        self.stop()
        self.control.confirm_stop(self.task['id'], self.task['digest'])
        self.restart()
        self.idle_resource()
        self.service.tick()
        self.assertTrue(self.store.get(self.task['id'])['internal']['stop_confirmed'])
        self.assert_next_dispatched()

    def test_confirmed_single_delete_preserves_records_files_and_release_policy(self):
        self.blocked()
        self.stop()
        self.store.metadata('resource_policy', {'release_when_queue_idle': True})
        self.platform.resources['owned'] = {'id': 'owned', 'status': 'online', 'owned_by_gpuq': True, 'release_when_done': True}
        self.control.stop(self.following['id'], self.following['digest'])
        self.platform.resources['original'] = {'id': 'original', 'status': 'closed'}
        kept = [self.folder/'run/dispatch.json', self.folder/'run/step-0.log', self.folder/'outputs/result.txt']
        for path in kept[1:]:
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text('kept')
        before = [p.read_bytes() for p in kept]
        self.service.tick()
        state = self.control.state()
        with self.assertRaises(ControlError): self.control.cleanup([self.task['id']], state['revision'])
        with self.assertRaises(ControlError): self.control.delete(self.task['id'], 'stale')
        self.control.delete(self.task['id'], self.task['digest'])
        self.restart()
        self.service.tick()
        self.assertNotIn(self.task['id'], [t['id'] for t in self.control.state()['tasks']])
        self.assertEqual([p.read_bytes() for p in kept], before)
        self.assertEqual(self.store.get(self.task['id'])['internal']['dispatch'], 'unknown')
        release = self.platform.resources['owned']['release']
        self.assertEqual(release['state'], 'pending_interface')
        self.assertFalse(release['released'])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM queue_audit WHERE task_id=? AND action LIKE 'delete_record:%'", (self.task['id'],)).fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM queue_audit WHERE task_id=? AND action LIKE 'browser_stop:%'", (self.task['id'],)).fetchone()[0], 1)

    def test_unclaimed_cancel_and_completed_result_keep_existing_behavior(self):
        cancelled = self.stop()
        self.assertEqual(cancelled['state'], 'cancelled')
        task = self.store.get(self.following['id'])
        task['public'].update(state='completed', step_records=[{'state': 'completed', 'outputs': ['saved']}])
        self.store.save(task)
        before = self.control.state()
        self.assertEqual(self.control.stop(task['id'], task['digest']), before)
        self.service.tick()
        self.assertEqual(self.store.get(task['id'])['public']['step_records'][0]['outputs'], ['saved'])
        self.assertEqual(self.store.get(task['id'])['public']['state'], 'completed')
        self.platform.submit_job.assert_not_called()
        self.platform.request.assert_not_called()

    def test_late_completed_runner_keeps_results_when_stop_was_requested(self):
        self.blocked()
        self.stop()
        self.service.tick()
        self.receipt()
        atomic_json(self.folder/'run/status.json', {'state': 'completed', 'stage': 1,
            'started_at': time.time()-10, 'updated_at': time.time(), 'finished_at': time.time(),
            'steps': [{'state': 'completed', 'outputs': ['saved-result']}]})
        (self.folder/'run/step-0.log').write_text('saved log')
        self.idle_resource()
        self.service.tick()
        self.assert_next_dispatched()
        self.restart()
        self.service.tick()
        task = self.store.get(self.task['id'])
        self.assertEqual(task['public']['state'], 'completed')
        self.assertEqual(task['public']['step_records'][0]['outputs'], ['saved-result'])
        self.assertEqual(task['public']['step_records'][0]['log'], 'saved log')
        self.assertFalse(task['internal'].get('stop_confirmed'))
        self.assertEqual(next(t for t in self.control.state()['tasks'] if t['id']==task['id'])['state'], 'completed')


class SubmissionDeleteTests(unittest.TestCase):
    """Deleted versions stay deleted across CLI submissions and transaction races."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
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

    def race(self, *, existing=False, delete=True, rename_errno=None):
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
        rename = Path.rename
        collisions = []

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

        def competing_rename(source, destination):
            if (rename_errno is not None and
                    threading.current_thread() is not main_thread and
                    destination.is_dir()):
                collisions.append(rename_errno)
                raise OSError(rename_errno, os.strerror(rename_errno), str(destination))
            return rename(source, destination)

        target = (patch.object(self.store, 'connect', side_effect=gated_connect)
                  if existing else patch('gpuqueue.core.shutil.copy2', side_effect=gated_copy))
        with target, patch.object(Path, 'rename', competing_rename), ThreadPoolExecutor(max_workers=1) as pool:
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
        if rename_errno is not None:
            self.assertEqual(collisions, [rename_errno])

    def test_deletion_committed_before_existing_task_lookup_is_rejected(self):
        self.race(existing=True)

    def test_concurrent_insert_then_delete_before_final_submission_is_rejected(self):
        self.race()

    def test_concurrent_visible_insert_returns_existing_task_created_false(self):
        self.race(delete=False)

    def test_directory_collision_errnos_reach_final_database_decision(self):
        for error in [errno.EEXIST, errno.ENOTEMPTY]:
            for delete in [False, True]:
                with self.subTest(errno=error, deleted=delete):
                    self.manifest['submission_key'] = f'collision-{error}-{delete}'
                    self.race(delete=delete, rename_errno=error)

    def test_unrelated_snapshot_rename_errors_propagate(self):
        for error in [errno.EACCES, errno.ENOSPC]:
            with self.subTest(errno=error):
                before = self.snapshot()
                failure = OSError(error, os.strerror(error))
                with patch.object(Path, 'rename', side_effect=failure):
                    with self.assertRaises(OSError) as raised:
                        self.store.submit(self.manifest)
                self.assertIs(raised.exception, failure)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(list((self.store.root / 'tasks').glob('.prepare-*')))


if __name__=='__main__':unittest.main()
