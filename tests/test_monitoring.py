import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from gpuqueue.core import Store, atomic_json, read_json
from gpuqueue.platform import Markflow, PlatformError
from gpuqueue.telemetry import parse_sample, PROBE_SCRIPT

REQUEST = '11111111-1111-4111-8111-111111111111'
JOB = '22222222-2222-4222-8222-222222222222'

class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.store = Store(self.home/'queue')
        self.adapter = Markflow(self.store, dict(home=str(self.home), username='linlishuo'))
        self.resource = dict(id=REQUEST, status='unknown', ready_notice_consumed=True)
        self.adapter.resources = {REQUEST: self.resource}
        self.adapter.submit_job = Mock(return_value=JOB)
        self.adapter.lark = Mock(return_value=dict(messages=[]))

    def tearDown(self):
        self.temp.cleanup()

    def sample(self, name='NVIDIA GeForce RTX 4090', uid='GPU-4090', used=1000):
        return dict(at=time.time(), gpus=f'0, {uid}, {name}, 49140, {used}, 75, N/A', apps='')

    def complete(self, payload):
        self.resource['probe'] = dict(job=JOB, at=time.time())
        folder = self.adapter.job_folder(REQUEST)/JOB
        atomic_json(folder/'status.json', dict(state='finished', exit_code=0))
        (folder/'output.log').write_text('GPUQ_TELEMETRY='+json.dumps(payload))
        self.adapter.refresh_probe(self.resource)

    def test_unknown_allocation_recovers_after_idle_and_clears_old_error(self):
        self.resource.update(error='GPU 检查超时', probe_timeout={'at':'old'})
        self.adapter.refresh(active=False)
        self.adapter.submit_job.assert_called_once()
        self.complete(self.sample())
        self.assertEqual(self.resource['status'], 'online')
        self.assertNotIn('error', self.resource)
        self.assertNotIn('probe_timeout', self.resource)
        self.assertEqual(self.resource['telemetry']['gpus'][0]['name'], 'NVIDIA GeForce RTX 4090')

    def test_failure_backs_off_without_new_gpu_application(self):
        self.resource['probe'] = dict(job=JOB, at=time.time())
        atomic_json(self.adapter.job_folder(REQUEST)/JOB/'status.json', dict(state='failed', exit_code=7))
        self.adapter.refresh_probe(self.resource)
        self.assertGreater(self.resource['probe_retry_at'], time.time()+25)
        self.adapter.refresh_probe(self.resource)
        self.adapter.submit_job.assert_not_called()
        self.resource['probe_retry_at'] = 0
        self.adapter.refresh_probe(self.resource)
        self.adapter.submit_job.assert_called_once()
        self.assertEqual(self.resource['status'], 'unknown')

    def test_late_probe_is_retained_and_consumed_without_duplicate(self):
        self.resource.update(status='online', probe=dict(job=JOB, at=time.time()-120))
        self.adapter.refresh_probe(self.resource)
        self.assertEqual(self.resource['status'], 'unknown')
        self.assertEqual(self.resource['probe']['job'], JOB)
        self.adapter.refresh_probe(self.resource)
        self.adapter.submit_job.assert_not_called()
        self.complete(self.sample())
        self.assertEqual(self.resource['status'], 'online')

    def test_closed_failed_pending_and_unconfirmed_requests_never_probe(self):
        for state in ['closed', 'failed', 'pending', 'unknown']:
            resource = dict(id=REQUEST, status=state)
            self.adapter.refresh_probe(resource)
        self.adapter.submit_job.assert_not_called()

    def test_bad_sample_does_not_poison_registry_or_other_allocation(self):
        self.resource['telemetry'] = parse_sample(self.sample(), time.time())
        previous = self.resource['telemetry']
        sample = self.sample();sample['gpus'] = sample['gpus'].replace('75', 'NaN')
        self.complete(sample)
        self.assertIs(self.resource['telemetry'], previous)
        self.assertEqual(self.resource['status'], 'unknown')
        self.assertIsNone(self.resource['probe'])
        self.adapter.refresh()
        record = read_json(self.home/'.local/state/serverbox-gpu/registry.json')['resources'][0]
        self.assertEqual(record['gpus'][0]['utilization_gpu_pct'], 75)

    def test_topology_change_resets_parallel_admission_history(self):
        self.resource.update(telemetry=parse_sample(self.sample(uid='GPU-old'), time.time()),
                             samples=[dict(at=time.time()-100, utilization=0)])
        self.complete(self.sample(uid='GPU-new'))
        self.assertEqual(len(self.resource['samples']), 1)
        self.assertEqual(self.resource['telemetry']['gpus'][0]['uuid'], 'GPU-new')

    def test_old_or_future_sample_cannot_refresh_timestamp(self):
        self.resource['telemetry'] = parse_sample(self.sample(), time.time())
        old = self.resource['telemetry']['at']
        for stamp in [old-1, time.time()+50]:
            sample = self.sample();sample['at'] = stamp
            self.complete(sample)
            self.assertEqual(self.resource['telemetry']['at'], old)
            self.assertEqual(self.resource['status'], 'unknown')

    def test_ambiguous_probe_submit_reconciles_unique_spec_before_retry(self):
        self.adapter.submit_job.side_effect = PlatformError('回执不明')
        with self.assertRaises(PlatformError):
            self.adapter.refresh_probe(self.resource)
        submission = self.resource['probe_submission']
        self.resource['probe_retry_at'] = 0
        self.adapter.refresh_probe(self.resource)
        self.assertEqual(self.adapter.submit_job.call_count, 1)
        atomic_json(self.adapter.job_folder(REQUEST)/(JOB+'.json'), dict(argv=submission['argv']))
        self.adapter.refresh_probe(self.resource)
        self.assertEqual(self.resource['probe']['job'], JOB)
        self.assertNotIn('probe_submission', self.resource)
        self.assertEqual(self.adapter.submit_job.call_count, 1)

    def test_optional_counters_are_unknown_and_process_query_blocks_reuse(self):
        sample=self.sample();sample.update(gpus='0, GPU-test, H100, N/A, N/A, [Not Supported], N/A', apps_known=False)
        self.complete(sample)
        self.assertEqual(self.resource['status'], 'online')
        self.assertIsNone(self.resource['telemetry']['gpus'][0]['utilization'])
        self.assertEqual(self.resource['samples'][0]['utilization'], 100)
        self.resource['type']='H卡离线'
        task=dict(doc=dict(resources=dict(type='H卡离线',gpus=1,memory_gb=2)),internal={})
        self.assertIsNone(self.adapter.select(task, [])[0])

    def test_probe_script_collects_even_when_temperature_or_apps_unsupported(self):
        results=[subprocess.CompletedProcess([],1,'','unsupported'),
                 subprocess.CompletedProcess([],0,'0, GPU-test, H100, 81559, 100, 0',''),
                 subprocess.CompletedProcess([],1,'','unsupported')]
        with patch('subprocess.run',side_effect=results), patch('builtins.print') as output:
            exec(PROBE_SCRIPT, {})
        payload=json.loads(output.call_args.args[0].split('=',1)[1])
        self.assertFalse(payload['apps_known'])
        self.assertEqual(parse_sample(payload,time.time())['gpus'][0]['name'],'H100')

    def test_mixed_models_and_multiple_cards_are_parsed_without_name_mapping(self):
        sample=self.sample();sample['gpus']+='\n1, GPU-h100, NVIDIA H100 80GB HBM3, 81559, 40000, 88, 63'
        telemetry=parse_sample(sample,time.time())
        self.assertEqual(len(telemetry['gpus']),2)
        self.assertEqual(telemetry['gpus'][1]['temperature_c'],63)

if __name__ == '__main__':
    unittest.main()
