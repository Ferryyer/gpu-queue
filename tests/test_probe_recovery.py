import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

from gpuqueue.core import atomic_json
from gpuqueue.platform import Markflow, PROBE_SCRIPT


REQUEST = '11111111-1111-4111-8111-111111111111'
JOB = '22222222-2222-4222-8222-222222222222'


class ProbeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.task = dict(id='GQ-test', public=dict(state='running'), internal=dict(
            request_uuid=REQUEST, approved_at='browser', dispatch='submitted', job_uuid='compute'))
        self.store = Mock(root=self.home/'queue')
        self.store.metadata.return_value = {}
        self.store.tasks.return_value = [self.task]
        self.adapter = Markflow(self.store, dict(home=str(self.home)))
        self.adapter.check_auth = Mock()
        self.adapter.submit_job = Mock(return_value=JOB)
        self.resource = dict(id=REQUEST, status='unknown', probe_timeout=dict(at='old', job='old-probe'))
        self.runner = self.store.root/'tasks/GQ-test/run/status.json'
        self.write_runner()

    def tearDown(self):
        self.temp.cleanup()

    def write_runner(self, **changes):
        atomic_json(self.runner, dict(state='running', gpu_verified=True,
                                     updated_at=time.time(), **changes))

    def recover(self):
        self.adapter.recover_active_probe(self.resource)
        self.adapter.refresh_probe(self.resource)

    def test_fresh_runner_recovers_only_readonly_probe_and_needs_real_sample(self):
        self.recover()
        self.adapter.submit_job.assert_called_once_with(REQUEST,
            ['/usr/bin/python3', '-c', PROBE_SCRIPT], self.home)
        self.assertEqual(self.resource['status'], 'unknown')
        folder = self.adapter.job_folder(REQUEST)/JOB
        atomic_json(folder/'status.json', dict(state='finished', uid=os.getuid(), exit_code=0))
        stamp = time.time()
        (folder/'output.log').write_text('GPUQ_TELEMETRY='+json.dumps(dict(
            at=stamp, gpus='0, GPU-test, H100, 81559, 50000, 100, 60', apps='')))
        self.adapter.refresh_probe(self.resource)
        self.assertEqual(self.resource['status'], 'online')
        self.assertEqual(self.resource['telemetry']['at'], stamp)
        self.assertNotIn('monitor', self.resource)
        self.assertNotIn('probe_timeout', self.resource)

    def test_historical_running_receipt_without_fresh_runner_cannot_retry(self):
        for changes in [dict(updated_at=time.time()-91), dict(gpu_verified=False),
                        dict(updated_at=time.time()+10), dict(state='completed')]:
            atomic_json(self.runner, dict(dict(state='running', gpu_verified=True,
                        updated_at=time.time()), **changes))
            self.recover()
            self.adapter.submit_job.assert_not_called()
        self.write_runner()
        for state in ['stopped', 'completed', 'execution_unknown', 'cancelled']:
            self.task['public']['state'] = state
            self.recover()
            self.adapter.submit_job.assert_not_called()

    def test_pending_probe_is_kept_and_late_receipt_is_consumed_without_duplicates(self):
        self.resource.update(status='online', probe=dict(job=JOB, at=time.time()-101))
        specification = self.adapter.job_folder(REQUEST)/(JOB+'.json')
        atomic_json(specification, dict(argv=['read-only-probe']))
        self.adapter.refresh_probe(self.resource)
        self.assertTrue(specification.exists())
        self.assertEqual(self.resource['probe']['job'], JOB)
        for _ in range(3):
            self.recover()
        self.adapter.submit_job.assert_not_called()
        folder = self.adapter.job_folder(REQUEST)/JOB
        atomic_json(folder/'status.json', dict(state='finished', exit_code=0))
        (folder/'output.log').write_text('GPUQ_TELEMETRY='+json.dumps(dict(
            at=time.time(), gpus='0, GPU-test, H100, 81559, 1, 0, 30', apps='')))
        self.recover()
        self.assertEqual(self.resource['status'], 'online')
        self.adapter.submit_job.assert_not_called()

    def test_legacy_timeout_with_existing_specification_reconciles_same_job(self):
        old = self.adapter.job_folder(REQUEST)/'old-probe.json'
        atomic_json(old, dict(argv=['read-only-probe']))
        self.recover()
        self.adapter.submit_job.assert_not_called()
        self.assertEqual(self.resource['probe']['job'], 'old-probe')

    def test_retry_budget_is_persisted_and_stop_or_closure_prevents_recovery(self):
        self.resource['monitor'] = dict(at=time.time()-60, attempts=3, state='retry')
        self.recover()
        self.adapter.submit_job.assert_not_called()
        self.resource.pop('monitor')
        self.task['internal']['stop_requested_at'] = 'now'
        self.recover()
        self.adapter.submit_job.assert_not_called()
        self.task['internal'].pop('stop_requested_at')
        self.resource['status'] = 'closed'
        self.recover()
        self.adapter.submit_job.assert_not_called()

    def test_notification_latency_is_bounded_across_allocations(self):
        other = '33333333-3333-4333-8333-333333333333'
        self.adapter.resources = {key: dict(id=key, status='pending') for key in [REQUEST, other]}
        barrier = threading.Barrier(2, timeout=2)
        self.adapter.lark = Mock(side_effect=lambda *a, **kw: (barrier.wait(), dict(messages=[]))[1])
        self.adapter.refresh()
        self.assertEqual(self.adapter.lark.call_count, 2)
        self.adapter.submit_job.assert_not_called()

    def test_delayed_receipt_does_not_add_another_thirty_seconds_before_sampling(self):
        self.resource.update(status='online', probe_checked=time.time(),
                             telemetry=dict(at=time.time()-20))
        self.adapter.refresh_probe(self.resource)
        self.adapter.submit_job.assert_called_once()
        self.adapter.refresh_probe(self.resource)
        self.adapter.submit_job.assert_called_once()

    def test_each_new_task_start_samples_even_when_reusing_fresh_gpu(self):
        self.resource.update(status='online', probe_checked=time.time(), telemetry=dict(at=time.time()))
        self.adapter.resources = {REQUEST: self.resource}
        self.adapter.begin_task_sampling(self.task)
        self.adapter.submit_job.assert_called_once()
        self.assertEqual(self.resource['sampling_start']['task'], self.task['id'])
        # A repeated lifecycle notification reuses the outstanding query.
        self.adapter.begin_task_sampling(self.task)
        self.adapter.submit_job.assert_called_once()
        self.resource.update(probe=None, probe_checked=time.time(), telemetry=dict(at=time.time()))
        second = dict(self.task, id='GQ-second', internal=dict(self.task['internal'], job_uuid='compute-2'))
        self.adapter.begin_task_sampling(second)
        self.assertEqual(self.adapter.submit_job.call_count, 2)

    def test_start_waits_for_existing_probe_and_requests_post_start_sample(self):
        before = time.time()-1
        self.resource.update(status='online', probe=dict(job=JOB, at=before))
        self.adapter.resources = {REQUEST: self.resource}
        folder = self.adapter.job_folder(REQUEST)/JOB
        atomic_json(folder/'status.json', dict(state='finished', exit_code=0))
        (folder/'output.log').write_text('GPUQ_TELEMETRY='+json.dumps(dict(
            at=before, gpus='0, GPU-test, H100, 81559, 1, 0, 30', apps='')))
        self.adapter.begin_task_sampling(self.task)
        self.adapter.submit_job.assert_not_called()
        self.assertIn('sample_requested_at', self.resource)
        self.adapter.refresh_probe(self.resource)
        self.adapter.submit_job.assert_called_once()

    def test_no_sampling_for_unstarted_stopped_or_unready_task(self):
        self.adapter.resources = {REQUEST: self.resource}
        for status in ['pending', 'closed', 'failed', 'unknown']:
            self.resource['status'] = status
            self.adapter.begin_task_sampling(self.task)
        self.resource['status'] = 'online'
        for changes in [dict(approved_at=None), dict(dispatch='submitting'),
                        dict(job_uuid=None), dict(stop_requested_at='now')]:
            self.adapter.begin_task_sampling(dict(self.task, internal=dict(self.task['internal'], **changes)))
        self.adapter.submit_job.assert_not_called()
        self.assertNotIn('sampling_start', self.resource)

    def test_sampling_error_does_not_undo_computation_dispatch(self):
        self.resource['status'] = 'online'
        self.adapter.resources = {REQUEST: self.resource}
        self.adapter.submit_job.side_effect = OSError('probe transport unavailable')
        self.adapter.begin_task_sampling(self.task)
        self.assertEqual(self.task['internal']['dispatch'], 'submitted')
        self.assertEqual(self.task['internal']['job_uuid'], 'compute')
        self.assertEqual(self.resource['monitor']['state'], 'retry')


if __name__ == '__main__':
    unittest.main()
