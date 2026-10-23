import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock
from gpuqueue.core import Store, atomic_json, read_json
from gpuqueue.platform import Markflow, PlatformError, PROBE_SCRIPT, TRUSTED_SENDER
from gpuqueue.serverbox import publish

REQUEST = '11111111-1111-4111-8111-111111111111'
SECOND = '22222222-2222-4222-8222-222222222222'


class ServerBoxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.store = Store(self.home/'queue')
        self.adapter = Markflow(self.store, dict(home=str(self.home), username='linlishuo'))
        self.path = self.home/'.local/state/serverbox-gpu/registry.json'

    def tearDown(self):
        self.temp.cleanup()

    def resource(self, request=REQUEST):
        return dict(id=request, status='online', telemetry=dict(at=time.time(), host='gpu-host',
                    gpus=[dict(index=0, uuid='GPU-test', name='H100', total_mb=81559,
                               used_mb=40000, utilization=88, temperature_c=63)]))

    def test_registry_is_private_and_contains_no_credentials(self):
        resource = self.resource()
        resource['password'] = 'must-not-be-published'
        publish({REQUEST: resource}, self.home)
        record = read_json(self.path)['resources'][0]
        self.assertEqual(record['gpus'][0]['temperature_c'], 63)
        self.assertEqual(record['request'], REQUEST)
        self.assertEqual(self.path.stat().st_mode & 0o077, 0)
        self.assertNotIn('must-not-be-published', self.path.read_text())

    def test_existing_probe_collects_temperature_and_actual_gpu_time(self):
        self.assertIn('temperature.gpu', PROBE_SCRIPT)
        self.assertIn('time.time()', PROBE_SCRIPT)

    def test_probe_receipt_preserves_sample_time_and_old_format(self):
        for temperature in [', 63', '']:
            job = '33333333-3333-4333-8333-333333333333'
            stamp = time.time()-10
            folder = self.adapter.job_folder(REQUEST)/job
            atomic_json(folder/'status.json', dict(state='finished', exit_code=0))
            payload = dict(gpus='0, GPU-test, H100, 81559, 40000, 88'+temperature,
                           apps='', at=stamp, host='gpu-host')
            (folder/'output.log').write_text('GPUQ_TELEMETRY='+json.dumps(payload))
            resource = dict(id=REQUEST, status='ready', probe=dict(job=job, at=time.time()))
            self.adapter.refresh_probe(resource)
            self.assertEqual(resource['telemetry']['at'], stamp)
            self.assertEqual(resource['telemetry']['gpus'][0]['temperature_c'], 63 if temperature else None)

    def test_idle_refresh_tracks_closure_without_submitting_gpu_work(self):
        resource = self.resource()
        self.adapter.resources = {REQUEST: resource}
        self.adapter.lark = Mock(return_value=dict(messages=[dict(sender=dict(id=TRUSTED_SENDER),
                                  content='GPU已回收\n申请：'+REQUEST)]))
        self.adapter.submit_job = Mock()
        self.adapter.refresh(active=False)
        self.assertEqual(resource['status'], 'closed')
        self.assertEqual(read_json(self.path)['resources'][0]['status'], 'closed')
        self.adapter.submit_job.assert_not_called()

    def test_idle_online_resource_reuses_existing_probe_not_another_collector(self):
        self.adapter.resources = {REQUEST: self.resource()}
        self.adapter.lark = Mock(return_value=dict(messages=[]))
        self.adapter.submit_job = Mock(return_value=SECOND)
        self.adapter.refresh(active=False)
        argv = self.adapter.submit_job.call_args.args[1]
        self.assertEqual(argv, ['/usr/bin/python3', '-c', PROBE_SCRIPT])
        self.assertEqual(read_json(self.path)['resources'][0]['status'], 'online')

    def test_release_intent_is_not_reported_as_destroyed(self):
        resource = self.resource()
        resource['release'] = dict(state='pending_interface', released=False)
        publish({REQUEST: resource}, self.home)
        record = read_json(self.path)['resources'][0]
        self.assertTrue(record['release_pending'])
        self.assertEqual(record['status'], 'online')

    def test_pending_application_does_not_run_gpu_commands(self):
        self.adapter.resources = {REQUEST: dict(id=REQUEST, status='pending')}
        self.adapter.lark = Mock(return_value=dict(messages=[]))
        self.adapter.submit_job = Mock()
        self.adapter.refresh(active=False)
        self.adapter.submit_job.assert_not_called()
        self.assertEqual(read_json(self.path)['resources'][0]['status'], 'pending')

    def test_discovery_does_not_turn_a_failed_probe_back_into_an_application(self):
        folder = self.home/'.local/state/markflow-gpu-requests'/REQUEST
        atomic_json(folder/'request.json', dict(fields={'服务器用户名': 'linlishuo'}))
        atomic_json(folder/'state.json', dict(state='submitted'))
        self.adapter.discover()
        self.assertEqual(self.adapter.resources[REQUEST]['status'], 'pending')
        self.adapter.resources[REQUEST].update(status='unknown', error='GPU 检查超时')
        self.adapter.discover()
        self.assertEqual(self.adapter.resources[REQUEST]['status'], 'unknown')

    def test_notice_failure_still_reads_a_completed_probe_but_blocks_scheduling(self):
        resource = self.resource()
        job = '33333333-3333-4333-8333-333333333333'
        resource.update(probe=dict(job=job, at=time.time()))
        self.adapter.resources = {REQUEST: resource}
        folder = self.adapter.job_folder(REQUEST)/job
        atomic_json(folder/'status.json', dict(state='finished', exit_code=0))
        stamp = time.time()
        (folder/'output.log').write_text('GPUQ_TELEMETRY='+json.dumps(dict(
            gpus='0, GPU-test, H100, 81559, 40000, 88, 63', apps='', at=stamp)))
        self.adapter.lark = Mock(side_effect=PlatformError('notification unavailable'))
        self.adapter.submit_job = Mock()
        with self.assertRaisesRegex(PlatformError, 'notification unavailable'):
            self.adapter.refresh()
        self.assertEqual(read_json(self.path)['resources'][0]['collected_at'], stamp)
        self.assertIsNone(resource['probe'])
        self.adapter.submit_job.assert_not_called()

    def test_one_resource_failure_does_not_skip_other_resource_samples(self):
        first, second = self.resource(), self.resource(SECOND)
        self.adapter.resources = {REQUEST: first, SECOND: second}
        self.adapter.refresh_notice = Mock()
        def probe(resource):
            if resource['id'] == REQUEST:
                raise BlockingIOError(11, 'Resource temporarily unavailable')
            resource['telemetry']['at'] = 123
        self.adapter.refresh_probe = Mock(side_effect=probe)
        with self.assertRaises(BlockingIOError):
            self.adapter.refresh()
        records = {r['request']: r for r in read_json(self.path)['resources']}
        self.assertEqual(records[SECOND]['collected_at'], 123)


if __name__ == '__main__':
    unittest.main()
