import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch,Mock
from gpuqueue.core import Store,normalize,atomic_json,read_json,HOME
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

 def run_output_events(self, events, *, exit_code=0, steps=1):
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

if __name__=='__main__':unittest.main()
