"""Fixed-clock monitoring and publication tests; no real platform operations."""
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from gpuqueue.core import Store, atomic_json, read_json
from gpuqueue.control import Control
from gpuqueue.platform import Markflow, PlatformError, TRUSTED_SENDER
from gpuqueue.resources import TERMINAL_RETENTION
from gpuqueue.serverbox import publish
from gpuqueue.service import Service


REQUEST = '11111111-1111-4111-8111-111111111111'
SECOND = '22222222-2222-4222-8222-222222222222'
JOB = '33333333-3333-4333-8333-333333333333'
NOW = 1_800_000_000
WEEK = TERMINAL_RETENTION


def iso(stamp):
    return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat()


class MonitoringFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.store = Store(self.home/'queue')
        self.adapter = Markflow(self.store, dict(home=str(self.home), username='employee'))
        self.adapter.check_auth = Mock()
        self.adapter.lark = Mock(return_value=dict(messages=[]))
        self.adapter.submit_job = Mock(return_value=JOB)
        clock = patch('time.time', return_value=NOW)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.registry = self.home/'.local/state/serverbox-gpu/registry.json'

    def online(self, age=0):
        return dict(id=REQUEST, status='online', type='H卡离线', probe_checked=NOW,
                    telemetry=dict(at=NOW-age, apps=[], gpus=[dict(index=0,
                        uuid='GPU-test', name='test', total_mb=81920, used_mb=1, utilization=0)]))


class MonitoringTests(MonitoringFixture):
    def test_periods_use_actual_sample_time_in_both_ready_and_online(self):
        for status in ['ready', 'online']:
            for active, age, count in [(False, 59, 0), (False, 60, 1), (True, 9, 0), (True, 10, 1)]:
                with self.subTest(status=status, active=active, age=age):
                    resource = dict(self.online(age), status=status)
                    self.adapter.resources = {REQUEST: resource}
                    self.adapter.submit_job.reset_mock()
                    self.adapter.refresh(active=active)
                    self.assertEqual(self.adapter.submit_job.call_count, count)

    def test_idle_to_active_rechecks_ten_second_period_in_same_tick(self):
        resource = self.online(20)
        self.adapter.resources = {REQUEST: resource}
        self.adapter.refresh(active=False)
        self.adapter.submit_job.assert_not_called()
        self.adapter.refresh(active=True)
        self.adapter.submit_job.assert_called_once()

    def test_initial_and_explicit_samples_bypass_idle_period(self):
        for changes in [dict(probe_checked=0), dict(sample_requested_at=NOW-1)]:
            with self.subTest(changes=changes):
                resource = dict(self.online(2), **changes)
                self.adapter.resources = {REQUEST: resource}
                self.adapter.submit_job.reset_mock()
                self.adapter.refresh(active=False)
                self.adapter.submit_job.assert_called_once()
                self.adapter.refresh(active=False)
                self.adapter.submit_job.assert_called_once()

    def test_inflight_and_late_receipt_keep_exact_job_and_sample_time(self):
        resource = dict(self.online(60), probe=dict(job=JOB, at=NOW-101))
        self.adapter.resources = {REQUEST: resource}
        spec = self.adapter.job_folder(REQUEST)/(JOB+'.json')
        atomic_json(spec, dict(argv=['read-only-probe']))
        for active in [False, True, False]:
            self.adapter.refresh(active=active)
            self.assertEqual(resource['probe']['job'], JOB)
            self.assertEqual(resource['status'], 'unknown')
        self.adapter.submit_job.assert_not_called()
        folder = self.adapter.job_folder(REQUEST)/JOB
        atomic_json(folder/'status.json', dict(state='finished', exit_code=0))
        (folder/'output.log').write_text('GPUQ_TELEMETRY='+json.dumps(dict(
            at=NOW-60, gpus='0, GPU-test, test, 81920, 1, 0', apps='')))
        self.adapter.refresh(active=False)
        self.assertIsNone(resource['probe'])
        self.assertEqual(resource['telemetry']['at'], NOW-60)
        self.adapter.submit_job.assert_not_called()
        self.adapter.refresh(active=False)
        self.adapter.submit_job.assert_called_once()
        self.adapter.refresh(active=True)
        self.adapter.submit_job.assert_called_once()
        self.assertTrue(spec.exists())

    def test_selection_keeps_ninety_second_actual_telemetry_boundary(self):
        task = dict(internal={}, doc=dict(resources=dict(type='H卡离线', gpus=1, memory_gb=1)))
        for age, ready in [(89, True), (90, True), (90.001, False)]:
            with self.subTest(age=age):
                self.adapter.resources = {REQUEST: self.online(age)}
                selection, _ = self.adapter.select(task, [])
                self.assertEqual(selection is not None, ready)

    def test_web_ready_stage_keeps_real_sample_time_and_existing_ninety_second_boundary(self):
        (self.home/'step.py').write_text('pass')
        with patch('gpuqueue.core.HOME', self.home):
            task, _ = self.store.submit(dict(project=str(self.home), title='synthetic task',
                code_files=['step.py'], steps=[dict(argv=['/usr/bin/python3', '{code}/step.py'])]))
        task['public']['request_uuid'] = REQUEST
        self.store.save(task)
        control = Control(self.store)
        control.start(task['id'], task['digest'])
        service = Service({}, self.store, self.adapter)
        for age, stage in [(60, 'resource_ready'), (89.999, 'resource_ready'),
                           (90, 'checking_resources'), (91, 'checking_resources')]:
            with self.subTest(age=age):
                resource = self.online(age)
                self.adapter.resources = {REQUEST: resource}
                service.sync()
                state = control.state()
                self.assertEqual(state['tasks'][0]['queue_stage'], stage)
                self.assertEqual(state['heartbeat']['resources'][0]['telemetry']['at'], NOW-age)

    def test_tick_activity_includes_approved_work_and_unreconciled_dispatch_or_stop(self):
        task = dict(id='test', public=dict(state='ready'), internal=dict(position=0))
        self.store.tasks = Mock(return_value=[task])
        platform = Mock(resources={})
        platform.select.return_value = (None, 'waiting')
        platform.request.return_value = None
        self.store.save = Mock()
        service = Service({}, self.store, platform)
        for name in ['refresh_task', 'sync', 'process_stop', 'record_release_intents']:
            setattr(service, name, Mock())
        cases = [('ready', {}, False), ('queued', {}, False),
                 ('queued', dict(approved_at='browser'), True),
                 ('waiting_gpu', dict(approved_at='browser'), True),
                 ('running', dict(approved_at='browser', dispatch='submitted'), True),
                 ('dispatching', dict(approved_at='browser'), True),
                 ('execution_unknown', dict(approved_at='browser'), True),
                 ('stopping', dict(approved_at='browser'), True),
                 ('blocked', dict(approved_at='browser', dispatch='unknown'), True),
                 ('blocked', dict(approved_at='browser', dispatch='submitting'), True)]
        for state, internal, active in cases:
            with self.subTest(state=state, internal=internal):
                task.update(public=dict(state=state), internal=dict(position=0, **internal))
                platform.refresh.reset_mock()
                service.tick()
                platform.refresh.assert_called_once_with(active=active)


class RetentionTests(MonitoringFixture):
    def local(self, state='closed', **fields):
        folder = self.home/'.local/state/markflow-gpu-requests'/REQUEST
        atomic_json(folder/'request.json', dict(fields={'服务器用户名': 'employee'}))
        atomic_json(folder/'state.json', dict(state=state, **fields))
        return folder

    def lists(self):
        service = Service({}, self.store, self.adapter)
        service.remote = Mock(return_value=dict(revision=0, tasks=[]))
        service.sync()
        web = service.remote.call_args.args[1]['heartbeat']['resources']
        return {r['id'] for r in web}, {r['request'] for r in read_json(self.registry)['resources']}

    def assert_lists(self, expected):
        self.assertEqual(self.lists(), (set(expected), set(expected)))

    def test_local_terminal_mapping_boundary_restart_and_files_are_retained(self):
        for state in ['closed', 'failed', 'rejected', 'cancelled']:
            with self.subTest(state=state):
                self.adapter.resources = {}
                folder = self.local(state, closed_recorded_at=iso(NOW-WEEK+1))
                job = self.adapter.job_folder(REQUEST)/JOB
                atomic_json(job/'status.json', dict(state='finished', exit_code=0))
                (job/'output.log').write_text('retained audit log')
                atomic_json(job.parent/(JOB+'.json'), dict(argv=['synthetic']))
                before = {p: p.read_bytes() for root in [folder, job.parent]
                          for p in root.rglob('*') if p.is_file()}
                self.adapter.refresh()
                resource = self.adapter.resources[REQUEST]
                self.assertEqual(resource['status'], 'closed' if state == 'closed' else 'failed')
                self.assert_lists([REQUEST])
                self.clock.return_value = NOW+1
                restarted = Markflow(self.store, self.adapter.config)
                restarted.check_auth = Mock()
                restarted.lark = Mock()
                self.adapter = restarted
                self.adapter.refresh()
                self.assert_lists([])
                self.assertEqual(self.adapter.resources[REQUEST]['terminal_at'], NOW-WEEK+1)
                self.assertIn(REQUEST, self.store.metadata('resources'))
                self.assertEqual(before, {p: p.read_bytes() for p in before})
                self.clock.return_value = NOW

    def test_trusted_timezone_timestamp_is_preferred_over_invalid_first_field(self):
        self.local(closed_recorded_at='invalid',
                   closed_recorded_utc=dt.datetime.fromtimestamp(
                       NOW-WEEK, dt.timezone(dt.timedelta(hours=8))).isoformat())
        self.adapter.refresh()
        self.assertEqual(self.adapter.resources[REQUEST]['terminal_at'], NOW-WEEK)
        self.assert_lists([])

    def test_missing_or_invalid_terminal_time_gets_full_week_from_confirmation(self):
        for value in [None, 'invalid', '2020-01-01T00:00:00', iso(NOW+1),
                      0, -1, float('nan'), float('inf'), True, {}, []]:
            with self.subTest(value=value):
                self.adapter.resources = {}
                folder = self.local(closed_recorded_at=value, created_at=iso(NOW-2*WEEK))
                os.utime(folder, (NOW-2*WEEK, NOW-2*WEEK))
                self.adapter.discover()
                self.adapter.resources[REQUEST]['telemetry'] = dict(at=NOW-3*WEEK)
                self.adapter.persist()
                self.assertEqual(self.adapter.resources[REQUEST]['terminal_at'], NOW)
                self.clock.return_value = NOW+WEEK-1
                self.adapter = Markflow(self.store, self.adapter.config)
                self.adapter.refresh()
                self.assert_lists([REQUEST])
                self.clock.return_value = NOW+WEEK
                self.adapter.refresh()
                self.assert_lists([])
                self.assertTrue((folder/'request.json').is_file())
                self.clock.return_value = NOW

    def test_existing_terminal_metadata_without_directory_gets_persisted_first_seen_time(self):
        self.adapter.resources = {REQUEST: dict(id=REQUEST, status='failed')}
        self.adapter.refresh()
        self.assertEqual(self.store.metadata('resources')[REQUEST]['terminal_at'], NOW)
        self.clock.return_value = NOW+100
        self.adapter = Markflow(self.store, self.adapter.config)
        self.adapter.refresh()
        self.assertEqual(self.adapter.resources[REQUEST]['terminal_at'], NOW)
        self.assert_lists([REQUEST])

    def notice(self, title, stamp, **fields):
        return dict(sender=dict(id=TRUSTED_SENDER), create_time=stamp,
                    content=title+'\n申请：'+REQUEST, **fields)

    def test_trusted_terminal_notice_and_repeated_notice_keep_same_clock(self):
        for title, status in [('GPU已回收', 'closed'), ('本次GPU申请失败', 'failed')]:
            for stamp in [iso(NOW-WEEK+1), str((NOW-WEEK+1)*1000), (NOW-WEEK+1)*1000]:
                with self.subTest(title=title, stamp=stamp):
                    self.adapter.resources = {REQUEST: dict(id=REQUEST, status='pending')}
                    self.adapter.lark = Mock(return_value=dict(messages=[self.notice(title, stamp)]))
                    self.adapter.refresh()
                    self.assertEqual(self.adapter.resources[REQUEST]['status'], status)
                    self.assert_lists([REQUEST])
                    self.clock.return_value = NOW+1
                    self.adapter.refresh_notice(self.adapter.resources[REQUEST])
                    self.adapter.refresh()
                    self.assertEqual(self.adapter.resources[REQUEST]['terminal_at'], NOW-WEEK+1)
                    self.assert_lists([])
                    self.clock.return_value = NOW

    def test_duplicate_terminal_notices_prefer_valid_batch_evidence_before_fallback(self):
        for title in ['GPU已回收', '本次GPU申请失败']:
            for invalid in [None, 'invalid', iso(NOW+1)]:
                for reverse in [False, True]:
                    with self.subTest(title=title, invalid=invalid, reverse=reverse):
                        messages = [self.notice(title, iso(NOW-WEEK)), self.notice(title, invalid)]
                        if reverse:
                            messages.reverse()
                        self.adapter.resources = {REQUEST: dict(id=REQUEST, status='pending')}
                        self.adapter.lark = Mock(return_value=dict(messages=messages))
                        self.adapter.refresh()
                        self.assertEqual(self.adapter.resources[REQUEST]['terminal_at'], NOW-WEEK)
                        self.assert_lists([])
                        # Repeated notices and restarts cannot move the stored time.
                        self.clock.return_value = NOW+60
                        self.adapter = Markflow(self.store, self.adapter.config)
                        self.adapter.check_auth = Mock()
                        self.adapter.submit_job = Mock(return_value=JOB)
                        self.adapter.lark = Mock(return_value=dict(messages=messages))
                        self.adapter.refresh()
                        self.adapter.lark.assert_not_called()
                        self.assertEqual(self.adapter.resources[REQUEST]['terminal_at'], NOW-WEEK)
                        self.assert_lists([])
                        self.clock.return_value = NOW

    def test_notice_without_valid_time_uses_observation_not_old_ready_or_submission_time(self):
        for stamp in [None, 'bad', iso(NOW+10), '2020-01-01T00:00:00']:
            with self.subTest(stamp=stamp):
                self.adapter.resources = {REQUEST: dict(id=REQUEST, status='pending')}
                self.adapter.lark = Mock(return_value=dict(messages=[
                    self.notice('GPU已回收', stamp),
                    self.notice('GPU已启动并通过成员权限与共享盘检查', iso(NOW-2*WEEK)),
                ]))
                self.adapter.refresh()
                self.assertEqual(self.adapter.resources[REQUEST]['terminal_at'], NOW)
                self.assert_lists([REQUEST])

    def test_untrusted_deleted_unmatched_and_nonterminal_notices_cannot_hide_resource(self):
        messages = [self.notice('GPU已回收', iso(NOW-2*WEEK), deleted=True),
                    dict(self.notice('GPU已回收', iso(NOW-2*WEEK)), sender=dict(id='untrusted')),
                    dict(self.notice('GPU已回收', iso(NOW-2*WEEK)), content='GPU已回收\n申请：'+SECOND),
                    self.notice('通知：普通信息', iso(NOW-2*WEEK))]
        self.adapter.resources = {REQUEST: dict(id=REQUEST, status='pending')}
        self.adapter.lark = Mock(return_value=dict(messages=messages))
        self.adapter.refresh()
        self.assertNotIn('terminal_at', self.adapter.resources[REQUEST])
        self.assert_lists([REQUEST])

    def test_edited_notice_cannot_use_creation_time_before_terminal_content(self):
        for update_time in [None, iso(NOW-1)]:
            with self.subTest(update_time=update_time):
                self.adapter.resources = {REQUEST: dict(id=REQUEST, status='pending')}
                self.adapter.lark = Mock(return_value=dict(messages=[self.notice(
                    'GPU已回收', iso(NOW-2*WEEK), updated=True, update_time=update_time)]))
                self.adapter.refresh()
                self.assertEqual(self.adapter.resources[REQUEST]['terminal_at'], NOW if update_time is None else NOW-1)
                self.assert_lists([REQUEST])

    def test_nonterminal_statuses_and_probe_timeout_are_visible_even_with_old_timestamp(self):
        self.adapter.refresh_probe = Mock()
        for status in ['pending', 'ready', 'online', 'unknown']:
            with self.subTest(status=status):
                self.adapter.resources = {REQUEST: dict(id=REQUEST, status=status,
                    terminal_at=NOW-2*WEEK, probe_timeout=dict(job=JOB))}
                self.adapter.refresh()
                self.assert_lists([REQUEST])

    def test_refresh_error_and_service_cycle_still_filter_both_publications(self):
        self.adapter.resources = {REQUEST: dict(id=REQUEST, status='closed', terminal_at=NOW-WEEK),
                                  SECOND: dict(id=SECOND, status='pending')}
        self.adapter.lark = Mock(side_effect=PlatformError('synthetic notice failure'))
        service = Service({}, self.store, self.adapter)
        service.cycle()
        self.assertIn('synthetic notice failure', service.error)
        # Read the real local web control API's heartbeat after the error path.
        self.assertEqual({r['id'] for r in Control(self.store).state()['heartbeat']['resources']}, {SECOND})
        self.assert_lists([SECOND])
        self.assertIn(REQUEST, self.adapter.resources)

    def test_discovery_enumeration_error_still_expires_both_publications(self):
        folder = self.local(closed_recorded_at=iso(NOW-WEEK+1))
        self.adapter.resources = {SECOND: dict(id=SECOND, status='pending')}
        self.adapter.refresh()
        self.assert_lists([REQUEST, SECOND])
        before = {p: p.read_bytes() for p in folder.iterdir() if p.is_file()}
        self.clock.return_value = NOW+1
        base = folder.parent
        original = Path.iterdir

        def denied(path):
            if path == base:
                raise PermissionError('synthetic request directory denial')
            return original(path)

        service = Service({}, self.store, self.adapter)
        with patch.object(Path, 'iterdir', denied):
            service.cycle()
        self.assertIn('synthetic request directory denial', service.error)
        self.assertEqual({r['id'] for r in Control(self.store).state()['heartbeat']['resources']}, {SECOND})
        self.assert_lists([SECOND])
        self.assertEqual(self.store.metadata('resources')[REQUEST]['terminal_at'], NOW-WEEK+1)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.adapter.submit_job.assert_not_called()

    def test_begin_task_sampling_instant_publication_also_filters_expired_history(self):
        for error in [None, PlatformError('synthetic probe failure')]:
            with self.subTest(error=error):
                self.adapter.resources = {REQUEST: dict(id=REQUEST, status='failed', terminal_at=NOW-WEEK),
                                          SECOND: dict(self.online(), id=SECOND)}
                self.adapter.submit_job = Mock(return_value=JOB, side_effect=error)
                task = dict(id='test', public=dict(state='dispatching'), internal=dict(
                    approved_at='browser', dispatch='submitted', job_uuid='compute', request_uuid=SECOND))
                self.adapter.begin_task_sampling(task)
                self.adapter.submit_job.assert_called_once()
                self.assert_lists([SECOND])
                self.assertIn(REQUEST, self.adapter.resources)

    def test_publisher_conservatively_keeps_missing_or_invalid_terminal_metadata(self):
        for stamp in [None, 'invalid', float('inf'), NOW+1]:
            with self.subTest(stamp=stamp):
                self.adapter.resources = {REQUEST: dict(id=REQUEST, status='closed', terminal_at=stamp)}
                publish(self.adapter.resources, self.home)
                self.assert_lists([REQUEST])


if __name__ == '__main__':
    unittest.main()
