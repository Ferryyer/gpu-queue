import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from gpuqueue.control import Control
from gpuqueue.core import HOME, Store, read_json, atomic_json
from gpuqueue.platform import Markflow, PlatformError, TRUSTED_SENDER
from gpuqueue.service import Service


REQUEST = '11111111-1111-4111-8111-111111111111'


class RequestDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HOME/'scratch')
        self.home = Path(self.temp.name)
        self.store = Store(self.home/'queue')
        self.adapter = Markflow(self.store, {'home': str(self.home), 'username': 'linlishuo'})
        self.service = Service({}, self.store, self.adapter)
        self.control = Control(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def task(self):
        project = self.home/'project'
        project.mkdir(exist_ok=True)
        (project/'step.py').write_text('pass\n')
        task, _ = self.store.submit({
            'schema_version': 1, 'title': 'single GPU', 'project': str(project),
            'code_files': ['step.py'], 'resources': {'gpus': 1, 'memory_gb': 2, 'estimated_hours': 1},
            'steps': [{'name': 'step', 'argv': ['/usr/bin/python3', '{code}/step.py'], 'outputs': []}],
        })
        self.control.start(task['id'], task['digest'])
        return task

    def notice(self, title, message='ready-original'):
        return dict(sender=dict(id=TRUSTED_SENDER), message_id=message,
                    content=title+'\n申请：'+REQUEST)

    def test_historical_ready_notice_does_not_restart_timed_out_probes(self):
        resource = dict(id=REQUEST, status='unknown', ready_message='ready-original',
                        error='GPU 检查超时', samples=[])
        self.adapter.resources = {REQUEST: resource}
        self.adapter.lark = Mock(return_value=dict(messages=[
            self.notice('GPU已启动并通过成员权限与共享盘检查'),
            self.notice('GPU已启动并通过成员权限与共享盘检查', 'another-historical-ready'),
        ]))
        self.adapter.submit_job = Mock()
        self.adapter.refresh()
        self.assertEqual(resource['status'], 'unknown')
        self.adapter.submit_job.assert_not_called()
        # Also survives an adapter restart using persisted metadata.
        restarted = Markflow(self.store, self.adapter.config)
        restarted.lark = self.adapter.lark
        restarted.submit_job = Mock()
        restarted.resources[REQUEST]['notice_checked'] = 0
        restarted.refresh()
        restarted.submit_job.assert_not_called()

    def test_first_ready_notice_still_allows_one_probe_and_closure_wins(self):
        resource = dict(id=REQUEST, status='pending')
        self.adapter.resources = {REQUEST: resource}
        self.adapter.lark = Mock(return_value=dict(messages=[self.notice('GPU已启动并通过成员权限与共享盘检查')]))
        self.adapter.submit_job = Mock(return_value='probe-job')
        self.adapter.refresh()
        self.adapter.submit_job.assert_called_once()
        resource['notice_checked'] = 0
        self.adapter.lark.return_value = dict(messages=[self.notice('GPU已回收', 'closure')])
        self.adapter.refresh()
        self.assertEqual(resource['status'], 'closed')
        self.adapter.submit_job.assert_called_once()

    def test_unknown_old_resource_blocks_new_application_with_visible_reason(self):
        task = self.task()
        self.adapter.resources = {REQUEST: dict(id=REQUEST, status='unknown', error='GPU 检查超时')}
        self.adapter.refresh = Mock()
        self.adapter.lark = Mock()
        self.service.cycle()
        public = self.control.state()['tasks'][0]
        self.assertEqual(public['state'], 'waiting_gpu')
        self.assertIn(REQUEST, public['phase'])
        self.assertIn('暂停新增申请', public['phase'])
        self.assertIsNone(self.store.get(task['id'])['internal']['request_uuid'])
        self.adapter.lark.assert_not_called()

    def test_ambiguous_submission_is_not_reported_as_submitted(self):
        task = self.task()
        self.adapter.resources = {REQUEST: dict(id=REQUEST, status='pending', recorded_phase='submission_unknown')}
        selection, reason = self.adapter.select(task, [])
        self.assertIsNone(selection)
        self.assertIn('提交回执待核查', reason)
        self.assertNotIn('已提交', reason)

    def test_failure_and_recovery_are_published_in_same_cycle(self):
        task = self.task()
        self.adapter.refresh = Mock(side_effect=PlatformError('network unavailable'))
        self.adapter.request = Mock(return_value=None)
        self.service.cycle()
        state = self.control.state()
        self.assertEqual(state['heartbeat']['error'], 'network unavailable')
        self.assertIn('network unavailable', state['tasks'][0]['phase'])
        self.adapter.request.assert_not_called()
        self.adapter.refresh.side_effect = None
        self.adapter.resources = {REQUEST: dict(id=REQUEST, status='unknown')}
        self.service.cycle()
        state = self.control.state()
        self.assertIsNone(state['heartbeat']['error'])
        self.assertIn('可用状态待核查', state['tasks'][0]['phase'])
        self.assertIsNone(read_json(self.store.root/'service-status.json')['error'])

    def test_browser_approved_task_submits_once_and_persists_receipt(self):
        task = self.task()
        self.adapter.refresh = Mock()
        self.adapter.lark = Mock(side_effect=[{'questions': []}, {'record_id': 'receipt'}])
        self.service.cycle()
        task = self.store.get(task['id'])
        request = task['internal']['request_uuid']
        folder = self.home/'.local/state/markflow-gpu-requests'/request
        self.assertEqual(read_json(folder/'state.json')['state'], 'submitted')
        self.assertEqual(read_json(folder/'receipt.json'), {'record_id': 'receipt'})
        self.assertEqual(task['public']['request_uuid'], request)
        self.assertEqual(len(self.adapter.lark.call_args_list), 2)
        self.assertIn('+form-submit', self.adapter.lark.call_args_list[1].args[0])
        self.service.cycle()
        self.assertEqual(len(self.adapter.lark.call_args_list), 2)

    def test_form_timeout_retains_uuid_and_never_retries_submission(self):
        task = self.task()
        self.adapter.refresh = Mock()
        self.adapter.lark = Mock(side_effect=[{'questions': []}, subprocess.TimeoutExpired('form-submit', 90)])
        self.service.cycle()
        request = self.store.get(task['id'])['internal']['request_uuid']
        folder = self.home/'.local/state/markflow-gpu-requests'/request
        self.assertEqual(read_json(folder/'state.json')['state'], 'submission_unknown')
        self.service.cycle()
        self.assertEqual(len(self.adapter.lark.call_args_list), 2)
        self.assertIn('提交回执待核查', self.control.state()['tasks'][0]['phase'])

    def enable_replacement(self):
        self.store.metadata('resource_policy', {'replace_timed_out_gpu': True})
        resource = dict(id=REQUEST, status='unknown', recorded_phase='submitted',
                        ready_message='old-ready', type='H卡离线', gpus=1,
                        error='GPU 检查超时；不会据此重复申请')
        self.adapter.resources = {REQUEST: resource}
        self.adapter.refresh = Mock()
        return resource

    def test_timeout_policy_submits_one_replacement_and_keeps_old_state_unknown(self):
        task = self.task()
        old = self.enable_replacement()
        self.adapter.lark = Mock(side_effect=[{'questions': []}, {'record_id': 'new-receipt'}])
        self.service.cycle()
        task = self.store.get(task['id'])
        request = task['internal']['request_uuid']
        self.assertNotEqual(request, REQUEST)
        self.assertEqual(task['internal']['timeout_replacement']['prior_requests'], [REQUEST])
        state = read_json(self.home/'.local/state/markflow-gpu-requests'/request/'state.json')
        self.assertEqual(state['state'], 'submitted')
        self.assertEqual(state['timeout_replacement']['request'], request)
        self.assertEqual(old['status'], 'unknown')
        self.service.cycle()
        self.assertEqual(len(self.adapter.lark.call_args_list), 2)
        self.assertIn(request, self.control.state()['tasks'][0]['phase'])

    def test_replacement_budget_survives_restart_and_second_gpu_timeout(self):
        task = self.task()
        self.enable_replacement()
        self.adapter.lark = Mock(side_effect=[{'questions': []}, {'record_id': 'receipt'}])
        self.service.cycle()
        task = self.store.get(task['id'])
        request = task['internal']['request_uuid']
        self.adapter.resources[request].update(status='unknown', ready_message='new-ready',
                    error='GPU 检查超时', recorded_phase='submitted')
        self.adapter.persist()
        restarted = Markflow(self.store, self.adapter.config)
        restarted.refresh = Mock()
        restarted.lark = Mock()
        Service({}, self.store, restarted).cycle()
        restarted.lark.assert_not_called()
        self.assertIn('已补申请一次', self.control.state()['tasks'][0]['phase'])
        self.assertEqual(self.store.get(task['id'])['internal']['request_uuid'], request)

    def test_pending_or_ambiguous_submission_or_generic_unknown_cannot_replace(self):
        task = self.task()
        self.enable_replacement()
        self.service.sync()
        task = self.store.get(task['id'])
        for changes in [dict(status='pending'), dict(recorded_phase='submission_unknown'),
                        dict(error='notification network timeout'), dict(ready_message=None)]:
            with self.subTest(changes=changes):
                resource = self.enable_replacement()
                resource.update(changes)
                self.adapter.lark = Mock()
                self.assertIsNone(self.adapter.request(task))
                self.adapter.lark.assert_not_called()

    def test_timeout_replacement_does_not_authorize_unstarted_or_dispatched_tasks(self):
        task = self.task()
        self.enable_replacement()
        self.adapter.lark = Mock()
        with self.assertRaises(PlatformError):
            self.adapter.request(task)
        task['internal'].update(approved_at='browser', job_uuid='existing-job', dispatch='submitted')
        self.assertIsNone(self.adapter.request(task))
        self.adapter.lark.assert_not_called()

    def test_timeout_after_ready_before_dispatch_can_use_a_new_request_uuid(self):
        task = self.task()
        self.enable_replacement()
        self.service.sync()
        task = self.store.get(task['id'])
        task['internal']['request_uuid'] = REQUEST
        self.store.save(task)
        self.adapter.lark = Mock(side_effect=[{'questions': []}, {'record_id': 'receipt'}])
        self.service.cycle()
        self.assertNotEqual(self.store.get(task['id'])['internal']['request_uuid'], REQUEST)

    def test_form_timeout_on_replacement_preserves_new_uuid_without_retry(self):
        task = self.task()
        self.enable_replacement()
        self.adapter.lark = Mock(side_effect=[{'questions': []}, subprocess.TimeoutExpired('form-submit', 90)])
        self.service.cycle()
        task = self.store.get(task['id'])
        request = task['internal']['request_uuid']
        self.assertEqual(task['public']['request_uuid'], request)
        self.assertNotEqual(request, REQUEST)
        self.service.cycle()
        self.assertEqual(len(self.adapter.lark.call_args_list), 2)
        self.assertIn('提交回执待核查', self.control.state()['tasks'][0]['phase'])

    def test_existing_healthy_gpu_is_reused_before_requesting_replacement(self):
        self.task()
        self.enable_replacement()
        self.adapter.resources['healthy'] = dict(id='healthy', status='online', type='H卡离线',
            telemetry=dict(at=time.time(), gpus=[dict(uuid='GPU-ready', total_mb=81559, used_mb=1)], apps=[]))
        self.adapter.lark = Mock()
        self.service.dispatch = Mock()
        self.service.cycle()
        self.service.dispatch.assert_called_once()
        self.assertEqual(self.service.dispatch.call_args.args[1][0]['id'], 'healthy')
        self.adapter.lark.assert_not_called()

    def test_actual_probe_timeout_records_evidence_without_claiming_release(self):
        resource = dict(id=REQUEST, status='ready', probe=dict(job='unclaimed', at=time.time()-101))
        self.adapter.refresh_probe(resource)
        self.assertTrue(self.adapter.probe_timed_out(resource))
        self.assertEqual(resource['status'], 'unknown')
        self.assertEqual(resource['probe_timeout']['job'], 'unclaimed')

    def test_gpu_side_nvidia_query_timeout_is_eligible_for_replacement(self):
        resource = self.enable_replacement()
        resource.update(status='ready', probe=dict(job='gpu-side-timeout', at=time.time()))
        folder = self.adapter.job_folder(REQUEST)/'gpu-side-timeout'
        atomic_json(folder/'status.json', dict(state='finished', exit_code=124))
        (folder/'output.log').write_text('GPUQ_PROBE_TIMEOUT=1\n')
        self.adapter.refresh_probe(resource)
        self.assertTrue(self.adapter.probe_timed_out(resource))
        task = self.task()
        self.service.sync()
        self.assertEqual([r['id'] for r in self.adapter.replacement_candidates(self.store.get(task['id']))], [REQUEST])

    def test_generic_probe_failure_is_not_treated_as_timeout(self):
        resource = self.enable_replacement()
        resource.pop('error')
        resource.update(status='ready', probe=dict(job='failed-probe', at=time.time()))
        folder = self.adapter.job_folder(REQUEST)/'failed-probe'
        atomic_json(folder/'status.json', dict(state='finished', exit_code=124))
        (folder/'output.log').write_text('unrelated exit code\n')
        self.adapter.refresh_probe(resource)
        self.assertFalse(self.adapter.probe_timed_out(resource))

    def test_old_notice_failure_does_not_veto_authorized_timeout_replacement(self):
        task = self.task()
        old = self.enable_replacement()
        del self.adapter.refresh
        self.adapter.lark = Mock(side_effect=[PlatformError('old notice unavailable'),
                                             {'questions': []}, {'record_id': 'new-receipt'}])
        self.service.cycle()
        task = self.store.get(task['id'])
        self.assertIsNotNone(task['internal']['request_uuid'])
        self.assertEqual(old['notice_error'], 'old notice unavailable')
        self.assertIsNone(self.control.state()['heartbeat']['error'])

    def test_old_notice_failure_does_not_block_an_existing_replacement(self):
        task = self.task()
        old = self.enable_replacement()
        self.adapter.lark = Mock(side_effect=[{'questions': []}, {'record_id': 'receipt'}])
        self.service.cycle()
        new_request = self.store.get(task['id'])['internal']['request_uuid']
        old['notice_checked'] = 0
        del self.adapter.refresh
        def notices(args, **kwargs):
            if REQUEST in args:
                raise PlatformError('old notice unavailable')
            self.assertIn(new_request, args)
            return {'messages': []}
        self.adapter.lark = Mock(side_effect=notices)
        self.service.cycle()
        self.assertIsNone(self.control.state()['heartbeat']['error'])
        self.assertIn(new_request, self.control.state()['tasks'][0]['phase'])


if __name__ == '__main__':
    unittest.main()
