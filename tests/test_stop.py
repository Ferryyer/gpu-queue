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
from unittest.mock import Mock, patch
import uuid
from gpuqueue.core import HOME,Store,atomic_json,read_json
from gpuqueue.control import Control,ControlError,QueueChanged
from gpuqueue.service import Service
from gpuqueue import stop_control as stop

class StopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=HOME/'scratch',prefix='stop-qa-')
        self.root=Path(self.temp.name).resolve();self.project=self.root/'code';self.project.mkdir()
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
    def test_process_identity_and_parent_use_signal_visible_pids(self):
        process=subprocess.Popen(['/usr/bin/python3','-c','import time;time.sleep(30)'])
        self.processes.append(process)
        value=stop.identity(process.pid)
        self.assertIsNotNone(value)
        self.assertEqual(value['pid'],process.pid)
        self.assertEqual(value['ppid'],os.getpid())
        self.assertIn(process.pid,stop.table())
        self.assertIsNone(stop.identity(-1))
    def test_other_namespace_pid_collision_is_rejected(self):
        own = Path('/proc/self/status').read_text()
        mounted_pid = next(int(line.split()[1]) for line in own.splitlines() if line.startswith('Pid:'))
        if mounted_pid == os.getpid():
            self.skipTest('This case requires a procfs mounted from an ancestor PID namespace')
        folder = stop.proc_folder(os.getpid())
        self.assertIsNotNone(folder)
        with patch.object(stop, 'proc_folder', return_value=Path('/proc/0')):
            self.assertIsNone(stop.visible_pid(folder))
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

    def stop_dispatch_fixture(self, supervised=False):
        self.approve_claim()
        self.control.stop(self.task['id'], self.task['digest'])
        task = self.store.get(self.task['id'])
        task['internal'].update(approved_at='browser', dispatch='submitted',
                                request_uuid='original-request', job_uuid='original-compute')
        if supervised:
            task['internal']['argv'] = ['python3', 'supervise', str(self.folder)]
        self.store.save(task)
        self.jobs = self.root/'jobs'
        self.jobs.mkdir()
        self.platform = Mock()
        self.platform.resources = {}
        self.platform.job_folder.return_value = self.jobs
        self.platform.submit_job.side_effect = RuntimeError('submission uncertain')
        self.service = Service({}, self.store, self.platform)
        self.clock = self.enterContext(patch('gpuqueue.service.time.time', return_value=1000))

    def poll_stop(self, at, restart=False):
        self.clock.return_value = at
        if restart:
            self.service = Service({}, Store(self.store.root), self.platform)
        # Exercise refresh and both syncs, including the actual API state source.
        self.service.cycle()
        state = self.control.state()['tasks'][0]
        self.assertIn(state['state'], ['stopping', 'stopped', 'completed'])
        self.platform.request.assert_not_called()
        self.platform.select.assert_not_called()
        self.platform.begin_task_sampling.assert_not_called()
        self.platform.release.assert_not_called()
        return state

    def stop_proof(self, **changes):
        task = self.store.get(self.task['id'])
        proof = dict(state='stopped', mode='legacy', task=task['id'], digest=task['digest'],
                     stop_at=task['internal']['stop_requested_at'], uid=os.getuid(),
                     request='original-request', job='original-compute', processes=[])
        atomic_json(self.folder/'run/stop-result.json', {**proof, **changes})

    def stop_receipt(self, job):
        task = self.store.get(self.task['id'])
        atomic_json(self.jobs/(job+'.json'), {'argv': task['internal']['stop_argv']})

    def retry_audit(self):
        with self.store.connect() as db:
            return db.execute("SELECT action FROM queue_audit WHERE action LIKE 'stop_retry:%'").fetchall()

    def test_stop_submission_waits_60_seconds_then_resends_original_command_once(self):
        self.stop_dispatch_fixture()
        (self.folder/'outputs/kept.txt').write_text('existing artifact')
        self.assertIn('待核查', self.poll_stop(1000)['phase'])
        original = self.platform.submit_job.call_args
        saved = self.store.get(self.task['id'])['internal']
        self.assertEqual(saved['stop_submitted_at'], 1000)
        self.assertIn('original-compute', saved['stop_argv'])
        for at in [1001, 1059.999]:
            self.poll_stop(at, restart=True)
            self.assertEqual(self.platform.submit_job.call_count, 1)
        def retry(request, argv, cwd):
            internal = self.store.get(self.task['id'])['internal']
            self.assertEqual(internal['stop_retry_consumed_at'], 1060)
            self.assertEqual(len(self.retry_audit()), 1)
            return 'retry-control-job'
        self.platform.submit_job.side_effect = retry
        state = self.poll_stop(1060)
        self.assertEqual(self.platform.submit_job.call_args, original)
        self.assertEqual(original.args[0], 'original-request')
        self.assertEqual(original.args[2], str(self.project))
        self.assertEqual(self.platform.submit_job.call_count, 2)
        self.assertIn('已用完一次自动重发机会', state['phase'])
        for at in [1061, 2000]:
            self.assertEqual(self.poll_stop(at, restart=True)['state'], 'stopping')
        self.assertEqual(self.platform.submit_job.call_count, 2)
        self.assertEqual(len(self.retry_audit()), 1)
        self.assertEqual((self.folder/'outputs/kept.txt').read_text(), 'existing artifact')
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM queue_audit WHERE action LIKE 'browser_stop:%'").fetchone()[0], 1)

    def test_failed_retry_is_not_repeated_and_late_receipt_and_proof_are_accepted(self):
        self.stop_dispatch_fixture()
        self.poll_stop(1000)
        for at in [1060, 1200, 2000]:
            state = self.poll_stop(at, restart=True)
            self.assertEqual(state['state'], 'stopping')
            self.assertIn('待核查', state['phase'])
            self.assertIn('已用完一次自动重发机会', state['phase'])
        self.assertEqual(self.platform.submit_job.call_count, 2)
        self.assertEqual(len(self.retry_audit()), 1)
        self.stop_receipt('late-control')
        self.poll_stop(2001, restart=True)
        self.assertEqual(self.store.get(self.task['id'])['internal']['stop_job_uuid'], 'late-control')
        self.stop_proof(digest='other-version')
        self.assertEqual(self.poll_stop(2002)['state'], 'stopping')
        self.stop_proof()
        self.assertEqual(self.poll_stop(2003, restart=True)['state'], 'stopped')
        self.assertEqual(self.platform.submit_job.call_count, 2)

    def test_crash_at_retry_call_keeps_committed_budget_and_audit_after_restart(self):
        self.stop_dispatch_fixture()
        self.poll_stop(1000)
        class ProcessExit(BaseException):
            pass
        def crash(*args):
            self.assertEqual(self.store.get(self.task['id'])['internal']['stop_retry_consumed_at'], 1060)
            self.assertEqual(len(self.retry_audit()), 1)
            raise ProcessExit()
        self.platform.submit_job.side_effect = crash
        with self.assertRaises(ProcessExit):
            self.poll_stop(1060)
        for at in [1061, 5000]:
            self.poll_stop(at, restart=True)
        self.assertEqual(self.platform.submit_job.call_count, 2)
        self.assertEqual(len(self.retry_audit()), 1)

    def test_receipt_written_before_initial_submit_error_prevents_resend(self):
        self.stop_dispatch_fixture()
        def uncertain(*args):
            self.stop_receipt('first-control')
            raise RuntimeError('return lost after submission')
        self.platform.submit_job.side_effect = uncertain
        self.poll_stop(1000)
        self.poll_stop(1001, restart=True)
        self.assertEqual(self.store.get(self.task['id'])['internal']['stop_job_uuid'], 'first-control')
        self.poll_stop(2000)
        self.assertEqual(self.platform.submit_job.call_count, 1)
        self.assertFalse(self.retry_audit())

    def test_delayed_unique_receipt_at_deadline_prevents_resend(self):
        self.stop_dispatch_fixture()
        self.poll_stop(1000)
        self.stop_receipt('delayed-control')
        # Near matches and receipts from other allocations must be ignored.
        expected = self.store.get(self.task['id'])['internal']['stop_argv']
        atomic_json(self.jobs/'other-compute.json', {'argv': expected[:-1]+['other-compute']})
        atomic_json(self.root/'other-allocation/jobs/foreign.json', {'argv': expected})
        self.poll_stop(1060, restart=True)
        self.assertEqual(self.store.get(self.task['id'])['internal']['stop_job_uuid'], 'delayed-control')
        self.assertEqual(self.platform.submit_job.call_count, 1)
        self.assertFalse(self.retry_audit())

    def test_ambiguous_receipts_remain_evidence_and_never_trigger_retry(self):
        self.stop_dispatch_fixture()
        self.poll_stop(1000)
        self.stop_receipt('control-one')
        self.stop_receipt('control-two')
        state = self.poll_stop(1060, restart=True)
        self.assertIn('无法唯一确认', state['phase'])
        internal = self.store.get(self.task['id'])['internal']
        self.assertEqual(internal['stop_receipts'], ['control-one', 'control-two'])
        self.assertFalse(internal.get('stop_job_uuid'))
        (self.jobs/'control-two.json').unlink()
        self.poll_stop(2000, restart=True)
        self.assertFalse(self.store.get(self.task['id'])['internal'].get('stop_job_uuid'))
        (self.jobs/'control-one.json').unlink()
        self.poll_stop(3000)
        self.assertEqual(self.platform.submit_job.call_count, 1)
        self.assertFalse(self.retry_audit())
        self.stop_proof()
        self.assertEqual(self.poll_stop(3001)['state'], 'stopped')

    def test_unreadable_directory_or_receipt_never_counts_as_zero_matches(self):
        self.stop_dispatch_fixture()
        self.poll_stop(1000)
        for target in ['iterdir', 'read_text']:
            with self.subTest(target=target):
                if target == 'read_text':
                    self.stop_receipt('unreadable-control')
                original = getattr(Path, target)
                def unavailable(path, *args, **kwargs):
                    if path == self.jobs or path.parent == self.jobs:
                        raise PermissionError('receipt unavailable')
                    return original(path, *args, **kwargs)
                with patch.object(Path, target, unavailable):
                    # Patch only reconciliation; other cycle reads use Path too.
                    self.clock.return_value = 1060
                    self.service.process_stop(self.store.get(self.task['id']))
                self.service.sync()
                self.assertIn('读取失败', self.control.state()['tasks'][0]['phase'])
                self.assertEqual(self.platform.submit_job.call_count, 1)
        self.assertFalse(self.retry_audit())

    def test_malformed_missing_or_partial_receipts_block_resend(self):
        self.stop_dispatch_fixture()
        self.poll_stop(1000)
        for text in ['{', '{}', '[]', '{"argv":null}']:
            with self.subTest(receipt=text):
                (self.jobs/'broken.json').write_text(text)
                self.assertIn('读取失败', self.poll_stop(1060, restart=True)['phase'])
                self.assertEqual(self.platform.submit_job.call_count, 1)
        (self.jobs/'broken.json').unlink()
        self.jobs.rmdir()
        self.assertIn('读取失败', self.poll_stop(2000)['phase'])
        self.assertFalse(self.retry_audit())

    def test_legacy_submitting_record_waits_full_window_after_takeover(self):
        self.stop_dispatch_fixture()
        self.poll_stop(1000)
        task = self.store.get(self.task['id'])
        for key in ['stop_submitted_at', 'stop_cwd', 'stop_request_uuid']:
            task['internal'].pop(key)
        self.store.save(task)
        self.poll_stop(5000, restart=True)
        self.assertEqual(self.store.get(self.task['id'])['internal']['stop_submitted_at'], 5000)
        self.poll_stop(5059.999, restart=True)
        self.assertEqual(self.platform.submit_job.call_count, 1)
        self.poll_stop(5060, restart=True)
        self.assertEqual(self.platform.submit_job.call_count, 2)
        self.assertEqual(self.platform.submit_job.call_args_list[0], self.platform.submit_job.call_args_list[1])

    def test_retry_receipt_survives_lost_return_and_is_reconciled_after_restart(self):
        self.stop_dispatch_fixture()
        self.poll_stop(1000)
        def uncertain(*args):
            self.stop_receipt('retry-return-lost')
            raise RuntimeError('retry return lost')
        self.platform.submit_job.side_effect = uncertain
        self.poll_stop(1060)
        self.poll_stop(1061, restart=True)
        internal = self.store.get(self.task['id'])['internal']
        self.assertEqual(internal['stop_job_uuid'], 'retry-return-lost')
        self.assertEqual(internal['stop_dispatch'], 'submitted')
        self.poll_stop(2000, restart=True)
        self.assertEqual(self.platform.submit_job.call_count, 2)
        self.assertEqual(len(self.retry_audit()), 1)

    def test_partial_receipt_scan_preserves_already_discovered_match(self):
        self.stop_dispatch_fixture()
        self.poll_stop(1000)
        self.stop_receipt('observed-control')
        broken = self.jobs/'broken.json'
        broken.write_text('{')
        original = Path.iterdir
        def receipts(path):
            return iter([self.jobs/'observed-control.json', broken]) if path == self.jobs else original(path)
        with patch.object(Path, 'iterdir', receipts):
            self.assertIn('读取失败', self.poll_stop(1060)['phase'])
        self.assertEqual(self.store.get(self.task['id'])['internal']['stop_receipts'], ['observed-control'])
        (self.jobs/'observed-control.json').unlink()
        broken.unlink()
        self.assertIn('无法唯一确认', self.poll_stop(2000, restart=True)['phase'])
        self.assertEqual(self.platform.submit_job.call_count, 1)

    def test_late_proof_without_receipt_requires_full_stop_identity(self):
        self.stop_dispatch_fixture()
        self.poll_stop(1000)
        self.poll_stop(1060)
        for field, value in [('task', 'other-task'), ('digest', 'other-version'),
                             ('stop_at', 'other-stop'), ('uid', os.getuid()+1),
                             ('request', 'other-request'), ('job', 'other-compute')]:
            with self.subTest(field=field):
                self.stop_proof(**{field: value})
                self.assertEqual(self.poll_stop(2000, restart=True)['state'], 'stopping')
        self.stop_proof()
        self.assertEqual(self.poll_stop(2001)['state'], 'stopped')
        self.assertFalse(self.store.get(self.task['id'])['internal'].get('stop_job_uuid'))
        self.assertEqual(self.platform.submit_job.call_count, 2)

    def test_supervisor_confirms_within_15_seconds_without_control_submission(self):
        self.stop_dispatch_fixture(supervised=True)
        self.poll_stop(1000)
        self.poll_stop(1014.999, restart=True)
        self.platform.submit_job.assert_not_called()
        self.stop_proof(mode='supervisor', job=None)
        self.assertEqual(self.poll_stop(1014.999)['state'], 'stopped')
        self.platform.submit_job.assert_not_called()

    def test_supervisor_fallback_uses_its_own_60_second_receipt_window(self):
        self.stop_dispatch_fixture(supervised=True)
        self.poll_stop(1000)
        self.poll_stop(1015)
        self.assertEqual(self.platform.submit_job.call_count, 1)
        self.poll_stop(1074.999, restart=True)
        self.assertEqual(self.platform.submit_job.call_count, 1)
        self.poll_stop(1075)
        self.assertEqual(self.platform.submit_job.call_count, 2)

    def test_unverified_proof_before_or_after_retry_survives_full_cycle(self):
        self.stop_dispatch_fixture()
        self.poll_stop(1000)
        self.stop_proof(state='unverified', error='identity mismatch')
        state = self.poll_stop(1060, restart=True)
        self.assertEqual(state['state'], 'stopping')
        self.assertIn('identity mismatch', state['phase'])
        self.assertEqual(self.platform.submit_job.call_count, 1)
        (self.folder/'run/stop-result.json').unlink()
        self.poll_stop(1061)
        self.assertEqual(self.platform.submit_job.call_count, 2)
        self.stop_proof(state='unverified', error='identity mismatch')
        state = self.poll_stop(1062, restart=True)
        self.assertIn('identity mismatch', state['phase'])
        self.assertIn('已用完一次自动重发机会', state['phase'])
        self.assertEqual(state['state'], 'stopping')

    def test_exited_retry_control_without_valid_proof_stays_stopping(self):
        self.stop_dispatch_fixture()
        self.poll_stop(1000)
        self.platform.submit_job.side_effect = None
        self.platform.submit_job.return_value = 'retry-control'
        self.poll_stop(1060)
        atomic_json(self.jobs/'retry-control/status.json', {'state': 'finished'})
        (self.jobs/'retry-control/output.log').write_text('control command ended')
        self.stop_proof(stop_at='wrong-stop-request')
        state = self.poll_stop(1061, restart=True)
        self.assertEqual(state['state'], 'stopping')
        self.assertIn('已退出但未获得有效确认', state['phase'])
        self.assertIn('已用完一次自动重发机会', state['phase'])
        self.assertEqual(state['stop_log'], 'control command ended')
        # A matching identity with an unknown result state is not confirmation.
        self.stop_proof(state='invalid-result')
        self.assertIn('已退出但未获得有效确认', self.poll_stop(1061)['phase'])
        self.stop_proof()
        self.assertEqual(self.poll_stop(1062)['state'], 'stopped')
        self.assertEqual(self.platform.submit_job.call_count, 2)

    def test_existing_stop_branches_do_not_resend(self):
        self.stop_dispatch_fixture()
        self.poll_stop(1000)
        original = self.store.get(self.task['id'])
        for branch in ['completed', 'cancelled', 'not_dispatched', 'allocation_closed']:
            with self.subTest(branch=branch):
                task = json.loads(json.dumps(original))
                self.platform.resources = {}
                if branch in ['completed', 'cancelled']:
                    task['public']['state'] = branch
                elif branch == 'not_dispatched':
                    task['internal'].update(job_uuid=None, dispatch=None)
                else:
                    self.platform.resources = {'original-request': {'status': 'closed'}}
                self.clock.return_value = 1060
                self.service.process_stop(task)
                self.assertEqual(self.platform.submit_job.call_count, 1)
                self.assertEqual(task['public']['state'], branch if branch in ['completed', 'cancelled'] else 'stopped')

if __name__=='__main__':unittest.main()
