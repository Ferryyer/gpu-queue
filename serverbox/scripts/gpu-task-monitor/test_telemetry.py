import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location('telemetry', Path(__file__).with_name('telemetry.py'))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


class TelemetryTests(unittest.TestCase):
    def sample(self):
        return dict(schema=1, request='test', state='ok', collected_at=100,
                    gpus=t.parse_csv('0, GPU-test, NVIDIA H100 80GB HBM3, 87, 40230, 81559, 63\n'))

    def test_gpu_metrics_round_trip_into_serverbox_xml(self):
        xml = ET.fromstring(t.as_xml(self.sample()))
        self.assertEqual(xml.findtext('gpu/utilization/gpu_util'), '87 %')
        self.assertEqual(xml.findtext('gpu/temperature/gpu_temp'), '63 C')
        self.assertEqual(xml.findtext('gpu/fb_memory_usage/used'), '40230 MiB')
        self.assertIn('[GPU task]', xml.findtext('gpu/product_name'))

    def test_unavailable_is_not_zero(self):
        gpu = t.parse_csv('0, GPU-test, H100, N/A, 0, 81559, [N/A]')[0]
        self.assertIsNone(gpu['utilization_gpu_pct'])
        self.assertIsNone(gpu['temperature_c'])
        self.assertEqual(gpu['memory_used_mib'], 0)
        for bad in ['NaN', 'inf', '-1']:
            with self.assertRaises(ValueError):
                t.number(bad)

    def test_stale_error_stopped_and_future_samples_are_not_live(self):
        data = self.sample()
        self.assertTrue(t.fresh(data, now=115))
        self.assertFalse(t.fresh(data, now=121))
        self.assertFalse(t.fresh(data, now=90))
        for state in ['stopped', 'error']:
            self.assertFalse(t.fresh(dict(data, state=state), now=101))

    def test_atomic_private_snapshot_and_partial_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'request/latest.json'
            t.atomic_json(path, self.sample())
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            (root / 'partial').mkdir()
            (root / 'partial/latest.json').write_text('{')
            self.assertEqual(t.latest(root)['gpus'][0]['temperature_c'], 63)
            self.assertEqual(json.loads(path.read_text())['state'], 'ok')

    def registry(self, root, resources):
        t.atomic_json(root/'registry.json', dict(schema=1, source='gpuq', resources=resources))

    def record(self, request, status='online', stamp=100):
        return dict(request=request, status=status, collected_at=stamp,
                    gpus=self.sample()['gpus'], release_pending=False)

    def test_new_request_replaces_previous_and_old_close_does_not_hide_new(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.registry(root, [self.record('old', 'closed', 110), self.record('new', stamp=120)])
            data = t.latest(root)
            self.assertEqual(data['request'], 'new')
            self.assertTrue(t.fresh(data, now=140))

    def test_closed_registry_never_falls_back_to_live_legacy_collector(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            t.atomic_json(root/'legacy/latest.json', dict(self.sample(), collected_at=999))
            self.registry(root, [self.record('old', 'closed')])
            data = t.latest(root)
            self.assertEqual(data['state'], 'closed')
            self.assertFalse(t.fresh(data, now=101))

    def test_registry_refresh_does_not_refresh_old_gpu_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.registry(root, [self.record('new')])
            data = t.latest(root)
            self.assertTrue(t.fresh(data, now=185))
            self.assertFalse(t.fresh(data, now=191))
            self.assertFalse(t.fresh(data, now=90))

    def test_invalid_registry_metrics_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record = self.record('new')
            record['gpus'][0]['temperature_c'] = -1
            self.registry(root, [record])
            self.assertIsNone(t.latest(root))

    def test_pending_release_remains_live_and_unknown_is_not_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record = dict(self.record('new'), release_pending=True)
            self.registry(root, [record])
            self.assertTrue(t.fresh(t.latest(root), now=105))
            self.assertIn('待释放', t.status_text(t.latest(root), now=105))
            self.registry(root, [self.record('new', 'unknown')])
            text = t.status_text(t.latest(root), now=105)
            self.assertIn('待核查', text)
            self.assertNotIn('已销毁', text)

    def test_corrupt_registry_and_pending_registration_never_show_legacy_gpu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            t.atomic_json(root/'legacy/latest.json', self.sample())
            (root/'registry.json').write_text('{')
            self.assertFalse(t.fresh(t.latest(root), now=101))
            self.registry(root, [dict(request='new', status='pending', collected_at=0, gpus=[])])
            text = t.status_text(t.latest(root))
            self.assertIn('申请中', text)
            self.assertNotIn('1970', text)

    def test_query_disconnect_shows_recovery_until_fresh_sample_and_closure_wins(self):
        data = dict(self.sample(), source='gpuq', state='unknown', monitor={'state': 'retry'})
        self.assertIn('自动重连中', t.status_text(data, now=105))
        self.assertFalse(t.fresh(data, now=105))
        self.assertIn('自动核查中', t.status_text(dict(data, monitor={'state': 'waiting'}), now=105))
        self.assertIn('原查询回执', t.status_text(dict(data, monitor={'state': 'reconciling'}), now=105))
        self.assertIn('实时', t.status_text(dict(data, state='ok', monitor={}), now=105))
        closed = t.status_text(dict(data, state='closed'), now=105)
        self.assertIn('平台已确认', closed)
        self.assertNotIn('重连', closed)


if __name__ == '__main__':
    unittest.main()
