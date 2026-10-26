"""4090 handoff contract; isolated HOME, queue and mocked platform calls only."""
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock

from gpuqueue.control import Control
from gpuqueue.core import HOME, Store, normalize, read_json
from gpuqueue.platform import Markflow, TRUSTED_SENDER
from gpuqueue.service import Service


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HOME/'scratch')
        self.home = Path(self.temp.name)
        (self.home/'step.py').write_text('pass\n')
        self.manifest = {
            'schema_version': 1, 'title': '4090 contract', 'project': str(self.home),
            'code_files': ['step.py'],
            'resources': {'type': '4090联网', 'gpus': 1, 'memory_gb': None, 'estimated_hours': 1},
            'steps': [{'argv': ['/usr/bin/python3', '{code}/step.py']}],
        }
        self.store = Store(self.home/'queue')
        self.adapter = Markflow(self.store, {'home': str(self.home), 'username': 'linlishuo'})
        self.adapter.run = Mock(side_effect=AssertionError('external command forbidden'))
        self.adapter.submit_job = Mock(side_effect=AssertionError('GPU dispatch forbidden'))

    def tearDown(self):
        self.temp.cleanup()

    def cycle(self, approve=False):
        task, _ = self.store.submit(self.manifest)
        if approve:
            Control(self.store).start(task['id'], task['digest'])
        self.adapter.refresh = Mock()
        Service({}, self.store, self.adapter).cycle()
        return self.store.get(task['id'])

    def test_handoff_notification_fixtures(self):
        fixture = json.loads((Path(__file__).parent/'fixtures/4090-notifications.json').read_text())
        for case in fixture['cases']:
            with self.subTest(case=case['name']):
                initial = case.get('resource_status', 'pending')
                resource = dict(id=fixture['request_uuid'], status=initial)
                if case.get('ready_notice_consumed'):
                    resource['ready_notice_consumed'] = True
                self.adapter.lark = Mock(return_value={'messages': [{
                    'sender': {'id': TRUSTED_SENDER if case['trusted_sender'] else 'untrusted'},
                    'deleted': case['deleted'], 'content': case['content'], 'message_id': case['name'],
                }]})
                self.adapter.refresh_notice(resource)
                expected = {'ready_if_pending_and_not_consumed': 'ready',
                            'ignore_preserve_closed': 'closed', 'ignore': initial}.get(case['expected'], case['expected'])
                self.assertEqual(resource['status'], expected)
                if expected == 'failed':
                    self.assertNotIn('released', resource)
                    self.assertNotIn('release', resource)

    def test_title_only_classification_and_exact_uuid(self):
        request = '00000000-0000-4000-8000-000000004090'
        for title, label in [
            ('通知\n本次GPU申请失败', request),
            ('GPU已请求停止', request),
            ('GPU申请失败', request+'0'),
            ('GPU申请失败', request+'-extra'),
            ('GPU申请失败', request+'x'),
        ]:
            with self.subTest(title=title, label=label):
                resource = dict(id=request, status='pending')
                self.adapter.lark = Mock(return_value={'messages': [{
                    'sender': {'id': TRUSTED_SENDER}, 'content': title+'\n申请：'+label,
                }]})
                self.adapter.refresh_notice(resource)
                self.assertEqual(resource['status'], 'pending')

    def test_explicit_4090_and_default_h_card(self):
        self.assertEqual(normalize(self.manifest)[0]['resources']['type'], '4090联网')
        self.manifest['resources'] = {}
        self.assertEqual(normalize(self.manifest)[0]['resources'],
                         dict(type='H卡离线', gpus=1, memory_gb=None, estimated_hours=17))

    def test_estimated_hours_boundaries(self):
        for value in [2/60, 1, 17, math.nextafter(18, 0)]:
            with self.subTest(valid=value):
                self.manifest['resources']['estimated_hours'] = value
                normalize(self.manifest)
        for value in [0, -1, math.nextafter(2/60, 0), 18, 19, True, False, '1', float('nan'), float('inf')]:
            with self.subTest(invalid=value):
                self.manifest['resources']['estimated_hours'] = value
                with self.assertRaises(ValueError):
                    normalize(self.manifest)

    def test_unapproved_4090_never_requests_or_dispatches(self):
        self.adapter.lark = Mock()
        task = self.cycle()
        self.assertIsNone(task['internal']['approved_at'])
        self.adapter.lark.assert_not_called()
        self.adapter.submit_job.assert_not_called()

    def test_approved_4090_submission_persists_identity_and_uuid_before_http(self):
        def lark(args, **kwargs):
            if '+form-detail' in args:
                return {'questions': []}
            path = self.home/args[args.index('--json')+1][1:]
            request = read_json(path)['fields']
            state = read_json(path.parent/'state.json')
            self.assertEqual(request['资源类型'], '4090联网')
            self.assertEqual(request['卡数'], 1)
            self.assertEqual(request['服务器用户名'], 'linlishuo')
            self.assertEqual(state['request'], request['申请标识'])
            self.assertEqual(state['state'], 'submitting')
            self.assertEqual(state['authorization']['source'], 'gpuq_browser_start')
            return {'record_id': '4090-receipt'}
        self.adapter.lark = Mock(side_effect=lark)
        task = self.cycle(approve=True)
        self.assertEqual(read_json(self.home/'.local/state/markflow-gpu-requests'/task['internal']['request_uuid']/'receipt.json'),
                         {'record_id': '4090-receipt'})
        self.cycle()
        self.assertEqual(self.adapter.lark.call_count, 2)
        self.adapter.submit_job.assert_not_called()

    def test_4090_form_timeout_keeps_same_uuid_after_restart(self):
        self.adapter.lark = Mock(side_effect=[{'questions': []}, subprocess.TimeoutExpired('submit', 90)])
        task = self.cycle(approve=True)
        request = task['internal']['request_uuid']
        self.assertEqual(read_json(self.home/'.local/state/markflow-gpu-requests'/request/'state.json')['state'], 'submission_unknown')
        self.adapter = Markflow(self.store, self.adapter.config)
        self.adapter.lark = Mock(side_effect=AssertionError('no HTTP replay'))
        self.adapter.submit_job = Mock(side_effect=AssertionError('no GPU dispatch'))
        self.assertEqual(self.cycle()['internal']['request_uuid'], request)
        self.adapter.lark.assert_not_called()

    def test_closed_and_failed_resources_never_selected(self):
        task, _ = self.store.submit(self.manifest)
        for state in ['closed', 'failed']:
            self.adapter.resources = {'old': dict(id='old', status=state, type='4090联网',
                telemetry={'at': time.time(), 'gpus': [{'uuid': 'GPU-old', 'total_mb': 24576, 'used_mb': 0, 'utilization': 0}], 'apps': []})}
            self.assertIsNone(self.adapter.select(task, [])[0])

    def test_failure_notice_does_not_reapply_or_replay_compute(self):
        self.adapter.lark = Mock(side_effect=[{'questions': []}, {'record_id': 'receipt'}])
        task = self.cycle(approve=True)
        request = task['internal']['request_uuid']
        self.adapter.lark = Mock(return_value={'messages': [{
            'sender': {'id': TRUSTED_SENDER},
            'content': '本次GPU申请失败\n申请：'+request,
        }]})
        self.adapter.refresh_notice(self.adapter.resources[request])
        self.assertEqual(self.adapter.resources[request]['status'], 'failed')
        self.adapter.lark.reset_mock()
        self.adapter.lark.return_value = {'questions': []}
        again = self.cycle()
        self.assertEqual(again['internal']['request_uuid'], request)
        self.assertFalse(any('+form-submit' in call.args[0] for call in self.adapter.lark.call_args_list))
        self.adapter.submit_job.assert_not_called()

    def test_mixed_card_pending_or_unknown_keeps_global_guard(self):
        for state, phase in [('pending', 'submitted'), ('pending', 'submission_unknown'), ('unknown', 'submitted')]:
            with self.subTest(state=state, phase=phase):
                self.adapter.resources = {'h-card': dict(id='h-card', type='H卡离线', status=state, recorded_phase=phase)}
                self.adapter.lark = Mock()
                self.cycle(approve=True)
                self.adapter.lark.assert_not_called()


if __name__ == '__main__':
    unittest.main()
