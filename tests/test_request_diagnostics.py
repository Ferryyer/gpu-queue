import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from gpuqueue.control import Control
from gpuqueue.core import HOME, Store, read_json, atomic_json
from gpuqueue.feishu import SCOPES, FeishuAuthError, verify_user
from gpuqueue.platform import Markflow, PlatformError, TRUSTED_SENDER
from gpuqueue.service import Service


REQUEST = '11111111-1111-4111-8111-111111111111'


class RequestDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HOME/'scratch')
        self.home = Path(self.temp.name)
        self.store = Store(self.home/'queue')
        self.adapter = Markflow(self.store, {'home': str(self.home), 'username': 'linlishuo'})
        self.adapter.check_auth = Mock()
        self.service = Service({}, self.store, self.adapter)
        self.control = Control(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def task(self, title='single GPU'):
        project = self.home/'project'
        project.mkdir(exist_ok=True)
        (project/'step.py').write_text('pass\n')
        task, _ = self.store.submit({
            'schema_version': 1, 'title': title, 'project': str(project),
            'code_files': ['step.py'], 'resources': {'gpus': 1, 'memory_gb': 2, 'estimated_hours': 1},
            'steps': [{'name': 'step', 'argv': ['/usr/bin/python3', '{code}/step.py'], 'outputs': []}],
        })
        self.control.start(task['id'], task['digest'])
        return task

    def test_member_identity_checks_ignore_bot_and_distinguish_auth_failures(self):
        config = {'feishu_open_id': 'ou_member'}
        good = dict(openId='ou_member', available=True, verified=True, status='ready',
                    tokenStatus='valid', scope=' '.join(SCOPES))
        run = Mock()
        for change, code in [
            ({'available': False, 'status': 'missing', 'tokenStatus': 'missing'}, 'token_missing'),
            ({'available': False, 'status': 'missing', 'tokenStatus': 'expired'}, 'token_expired'),
            ({'openId': 'ou_other'}, 'wrong_identity'),
            ({'scope': 'offline_access'}, 'missing_scope'),
            ({'verified': False}, 'verification_failed'),
        ]:
            with self.subTest(code=code):
                run.return_value = subprocess.CompletedProcess([], 0, json.dumps({
                    'identity': 'bot', 'verified': True,
                    'identities': {'bot': {'available': True, 'verified': True},
                                   'user': dict(good, **change)},
                }), '')
                with self.assertRaises(FeishuAuthError) as caught:
                    verify_user(config, run)
                self.assertEqual(caught.exception.code, code)
        run.return_value = subprocess.CompletedProcess([], 1, '', json.dumps({
            'error': {'subtype': 'access_denied', 'message': 'untrusted CLI detail'},
        }))
        with self.assertRaises(FeishuAuthError) as caught:
            verify_user(config, run)
        self.assertEqual(caught.exception.code, 'access_denied')
        self.assertNotIn('untrusted CLI detail', str(caught.exception))

    def test_auth_recovery_after_restart_resumes_original_queue_once(self):
        first, second = self.task('first'), self.task('second')
        del self.adapter.check_auth
        self.adapter.config['feishu_open_id'] = 'ou_member'
        secret = 'must-not-leak-test-token'
        missing = dict(openId='ou_member', available=False, tokenStatus='missing')
        self.adapter.run = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps({
            'identities': {'bot': {'verified': True}, 'user': missing},
            'access_token': secret,
        }), ''))
        self.adapter.submit_job = Mock()
        self.service.cycle()
        self.service.cycle()
        self.adapter.run.assert_called_once()
        self.adapter.submit_job.assert_not_called()
        state = self.control.state()
        head, follower = state['tasks']
        self.assertEqual(head['queue_stage'], 'feishu_auth')
        self.assertEqual(follower['queue_stage'], 'predecessor')
        self.assertIn('等待飞书本人授权，尚未投放计算', follower['phase'])
        self.assertNotIn(secret, json.dumps(state))
        self.assertNotIn(secret, (self.store.root/'service-status.json').read_text())
        approved_at = head['approved_at']
        restarted = Markflow(self.store, self.adapter.config)
        good = dict(openId='ou_member', available=True, verified=True, tokenStatus='valid', scope=' '.join(SCOPES))
        def cli(argv, **kwargs):
            if 'status' in argv:
                return subprocess.CompletedProcess([], 0, json.dumps({'identities': {'user': good}}), '')
            self.assertEqual(argv[-2:], ['--as', 'user'])
            data = {'questions': []} if '+form-detail' in argv else {'can_submit_again': False, 'access_token': secret}
            return subprocess.CompletedProcess([], 0, json.dumps({'identity': 'user', 'ok': True, 'data': data}), '')
        restarted.run = Mock(side_effect=cli)
        restarted.submit_job = Mock()
        service = Service({}, self.store, restarted)
        service.cycle()
        service.cycle()
        self.control.start(first['id'], first['digest'])
        service.cycle()
        state = self.control.state()
        head, follower = state['tasks']
        self.assertEqual(head['approved_at'], approved_at)
        self.assertEqual(head['queue_stage'], 'request_submitted')
        self.assertEqual(follower['id'], second['id'])
        self.assertIsNone(follower.get('request_uuid'))
        self.assertEqual(sum('+form-submit' in call.args[0] for call in restarted.run.call_args_list), 1)
        restarted.submit_job.assert_not_called()
        request = self.home/'.local/state/markflow-gpu-requests'/head['request_uuid']
        self.assertEqual(read_json(request/'receipt.json'), {'can_submit_again': False})

    def test_ambiguous_request_blocks_reuse_until_durable_receipt_is_reconciled(self):
        task = self.task()
        folder = self.home/'.local/state/markflow-gpu-requests'/REQUEST
        atomic_json(folder/'request.json', {'fields': {'服务器用户名': 'linlishuo'}})
        atomic_json(folder/'state.json', {'request': REQUEST, 'state': 'submitting'})
        self.adapter.resources['available'] = dict(id='available', status='online', type='H卡离线',
            telemetry=dict(at=time.time(), gpus=[dict(uuid='GPU-1', total_mb=81920, used_mb=1)], apps=[]))
        self.adapter.discover()
        self.assertIsNone(self.adapter.select(task, [])[0])
        atomic_json(folder/'receipt.json', {'can_submit_again': False})
        self.adapter.discover()
        self.assertEqual(read_json(folder/'state.json')['state'], 'submitted')
        task['internal']['request_uuid'] = REQUEST
        selection, reason = self.adapter.select(task, [])
        self.assertIsNone(selection)
        self.assertIn('等待平台就绪', reason)

    def test_claimed_but_unrecorded_dispatch_and_failed_attempt_are_not_restarted(self):
        claimed = self.task('claimed')
        self.control.claim(claimed['id'], claimed['digest'], self.control.state()['revision'])
        failed = self.task('failed')
        failed['public']['state'] = 'failed'
        self.store.save(failed)
        self.adapter.submit_job = Mock()
        self.adapter.lark = Mock()
        self.service.cycle()
        self.assertEqual(self.store.get(claimed['id'])['internal']['dispatch'], 'unknown')
        self.assertEqual(self.store.get(failed['id'])['public']['state'], 'failed')
        self.adapter.submit_job.assert_not_called()
        self.adapter.lark.assert_not_called()

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
        restarted.check_auth = Mock()
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
        restarted.check_auth = Mock()
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
