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
  self.assertEqual(intent['state'],'grace_period');self.assertFalse(intent['released'])
  self.assertEqual(intent['release_after']-intent['idle_since'],5400)
  self.assertEqual(adapter.resources[rid]['status'],'online');adapter.run.assert_not_called()
  service.record_release_intents([first,second]);self.assertEqual(intent,read_json(self.store.root/'release-intents'/(rid+'.json')))
 def test_unapproved_tasks_do_not_hold_a_card(self):
  service,adapter,rid=self.release_service();task=self.task()
  service.record_release_intents([task]);self.assertEqual(adapter.resources[rid]['release']['state'],'grace_period')
 def test_uncertain_execution_or_submission_does_not_mark_queue_done(self):
  service,adapter,rid=self.release_service();task=self.task();task['internal']['approved_at']='now'
  task['public']['state']='execution_unknown';service.record_release_intents([task]);self.assertEqual(adapter.resources[rid]['release']['state'],'armed')
  task['public']['state']='blocked';task['internal']['dispatch']='unknown';service.record_release_intents([task]);self.assertEqual(adapter.resources[rid]['release']['state'],'armed')
 def test_only_service_owned_resources_get_release_intents(self):
  service,adapter,rid=self.release_service();adapter.resources[rid]['owned_by_gpuq']=False
  service.record_release_intents([]);self.assertNotIn('release',adapter.resources[rid])
  self.assertFalse((self.store.root/'release-intents'/(rid+'.json')).exists())

 def test_release_waits_full_90_minutes_and_survives_service_restart(self):
  service,adapter,rid=self.release_service();task=self.task()
  task['internal']['approved_at']='now';task['public']['state']='completed'
  with patch('gpuqueue.service.time.time',return_value=1000):service.record_release_intents([task])
  initial=read_json(self.store.root/'release-intents'/(rid+'.json'))
  # Recreate both service and adapter from persisted metadata, not process memory.
  adapter=Markflow(self.store,{'username':'linlishuo','home':str(self.root)})
  adapter.run=Mock();service=Service({},self.store,adapter)
  with patch('gpuqueue.service.time.time',return_value=6399):service.record_release_intents([task])
  self.assertEqual(read_json(self.store.root/'release-intents'/(rid+'.json')),initial)
  with patch('gpuqueue.service.time.time',return_value=6400):service.record_release_intents([task])
  release=adapter.resources[rid]['release']
  self.assertEqual(release['state'],'pending_interface');self.assertFalse(release['released'])
  self.assertEqual(release['idle_since'],1000);self.assertEqual(adapter.resources[rid]['status'],'online')
  adapter.run.assert_not_called()

 def test_new_approved_task_cancels_and_restarts_grace_period(self):
  service,adapter,rid=self.release_service();task=self.task()
  task['internal']['approved_at']='now';task['public']['state']='completed'
  with patch('gpuqueue.service.time.time',return_value=1000):service.record_release_intents([task])
  self.manifest['title']='new approved task';second=self.task()
  second['internal']['approved_at']='later';second['public']['state']='queued'
  with patch('gpuqueue.service.time.time',return_value=6000):service.record_release_intents([task,second])
  self.assertEqual(adapter.resources[rid]['release']['state'],'armed')
  self.assertNotIn('release_after',adapter.resources[rid]['release'])
  second['public']['state']='completed'
  with patch('gpuqueue.service.time.time',return_value=6500):service.record_release_intents([task,second])
  self.assertEqual(adapter.resources[rid]['release']['release_after'],11900)

 def test_task_completed_during_downtime_also_restarts_grace_period(self):
  service,adapter,rid=self.release_service();task=self.task()
  task['internal']['approved_at']='now';task['public']['state']='completed'
  with patch('gpuqueue.service.time.time',return_value=1000):service.record_release_intents([task])
  self.manifest['title']='completed during downtime';second=self.task()
  second['internal']['approved_at']='later';second['public']['state']='completed'
  with patch('gpuqueue.service.time.time',return_value=7000):service.record_release_intents([task,second])
  self.assertEqual(adapter.resources[rid]['release']['state'],'grace_period')
  self.assertEqual(adapter.resources[rid]['release']['release_after'],12400)

 def test_old_immediate_intent_migrates_to_full_grace_period(self):
  service,adapter,rid=self.release_service()
  adapter.resources[rid]['release']={'state':'pending_interface','released':False,'at':'old'}
  with patch('gpuqueue.service.time.time',return_value=1000):service.record_release_intents([])
  self.assertEqual(adapter.resources[rid]['release']['release_after'],6400)
  self.assertEqual(adapter.resources[rid]['release']['state'],'grace_period')

 def test_disabling_policy_clears_timer_and_reenabling_starts_fresh(self):
  service,adapter,rid=self.release_service()
  with patch('gpuqueue.service.time.time',return_value=1000):service.record_release_intents([])
  self.store.metadata('resource_policy',{'release_when_queue_idle':False})
  service.record_release_intents([])
  self.assertEqual(adapter.resources[rid]['release']['state'],'disabled')
  self.assertNotIn('release_after',adapter.resources[rid]['release'])
  self.store.metadata('resource_policy',{'release_when_queue_idle':True})
  with patch('gpuqueue.service.time.time',return_value=7000):service.record_release_intents([])
  self.assertEqual(adapter.resources[rid]['release']['release_after'],12400)

 def test_clock_rollback_and_invalid_persisted_time_restart_safely(self):
  service,adapter,rid=self.release_service()
  with patch('gpuqueue.service.time.time',return_value=1000):service.record_release_intents([])
  with patch('gpuqueue.service.time.time',return_value=900):service.record_release_intents([])
  self.assertEqual(adapter.resources[rid]['release']['release_after'],6300)
  for invalid in [None,'900',float('nan'),float('inf'),True,-1]:
   adapter.resources[rid]['release']['idle_since']=invalid
   with patch('gpuqueue.service.time.time',return_value=2000):service.record_release_intents([])
   self.assertEqual(adapter.resources[rid]['release']['release_after'],7400)

 def test_closed_failed_and_opted_out_resources_are_untouched(self):
  for status,opted_in in [('closed',True),('failed',True),('online',False)]:
   service,adapter,rid=self.release_service()
   adapter.resources[rid].update(status=status,release_when_done=opted_in)
   service.record_release_intents([]);self.assertNotIn('release',adapter.resources[rid])

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
