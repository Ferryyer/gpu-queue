"""Isolated submission boundaries and durable local control regressions."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from gpuqueue import cli
from gpuqueue.core import Store, atomic_json, canonical, normalize, read_json
from gpuqueue.control import Control
from gpuqueue.service import Service


class SnapshotPathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.project = self.home/'project'
        (self.project/'src').mkdir(parents=True)
        (self.project/'src/train.py').write_text('print("fixture")\n')
        (self.project/'config.json').write_text('{}')
        (self.project/'data.txt').write_text('data')
        self.addCleanup(patch.stopall)
        patch('gpuqueue.core.HOME', self.home).start()
        patch('pathlib.Path.home', return_value=self.home).start()
        self.store = Store(self.home/'queue')
        self.manifest = {
            'title': 'synthetic path fixture', 'project': str(self.project),
            'code_files': ['src', 'config.json'],
            'steps': [{'argv': ['/usr/bin/python3', '{code}/src/train.py']}],
        }

    def reject(self, argument, cwd=None, message='运行代码请引用'):
        manifest = deepcopy(self.manifest)
        step = manifest['steps'][0]
        step['argv'][1] = argument
        if cwd is not None:
            step['cwd'] = cwd
        with self.assertRaisesRegex(ValueError, message):
            normalize(manifest)
        with self.assertRaisesRegex(ValueError, message):
            self.store.submit(manifest)
        self.assertEqual(self.store.tasks(), [])
        self.assertFalse((self.store.root/'tasks').exists())

    def test_source_path_equivalence_in_arguments_and_equals_options(self):
        for value, cwd in [
            (str(self.project/'src/train.py'), None),
            ('{project}/src/../config.json', None),
            ('{project}/../project/src/train.py', None),
            ('{home}/project/src/./train.py', None),
            ('src/train.py', '{project}'),
            ('./train.py', '{project}/src'),
            ('../config.json', '{project}/src'),
            ('src/../config.json', str(self.project)),
            ('project/src/train.py', '{home}'),
            ('train.py', '{project}/src/../src'),
        ]:
            for argument in [value, '--script='+value]:
                with self.subTest(argument=argument, cwd=cwd):
                    self.reject(argument, cwd)

    def test_source_symlink_targets_and_snapshot_index_are_checked(self):
        (self.home/'alias.py').symlink_to(self.project/'src/train.py')
        (self.project/'src/linked.py').symlink_to(self.project/'config.json')
        self.manifest['code_files'] = ['src']
        for value in ['{project}/src/linked.py', '{project}/config.json']:
            self.reject(value)
        for value in ['{home}/alias.py', '--script={home}/alias.py']:
            self.reject(value)
        (self.home/'work').symlink_to(self.project/'src', target_is_directory=True)
        self.reject('train.py', '{home}/work')
        self.manifest['steps'][0]['argv'][1] = '{code}/src/linked.py'
        task, _ = self.store.submit(self.manifest)
        copied = self.store.root/'tasks'/task['id']/'code/src/linked.py'
        self.assertFalse(copied.is_symlink())
        self.assertEqual(copied.read_text(), '{}')

    def test_snapshot_escapes_and_missing_references_are_rejected(self):
        for value, cwd in [
            ('{code}/../config.json', None),
            ('{code}/src/../../data.txt', None),
            ('{code}/src/../missing.py', None),
            ('{code}/data.txt', None),
            ('{code}/missing.py', '{code}/src'),
        ]:
            for argument in [value, '--config='+value]:
                with self.subTest(argument=argument, cwd=cwd):
                    self.reject(argument, cwd, '快照')

    def test_valid_paths_preserve_manifest_and_digest(self):
        (self.home/'external.txt').write_text('external data')
        (self.home/'project-other').mkdir()
        (self.home/'project-other/config.json').write_text('{}')
        for value, cwd in [
            ('{code}', None),
            ('{code}/.', None),
            ('{code}/src/..', None),
            ('{code}/src/../config.json', None),
            ('{code}/src', None),
            ('src/./train.py', None),
            ('train.py', '{code}/src'),
            ('../config.json', '{code}/src'),
            ('{project}/data.txt', None),
            ('data.txt', '{project}'),
            ('external.txt', '{home}'),
            ('{home}/external.txt', None),
            ('{home}/project-other/config.json', None),
            ('{outputs}/result.json', None),
        ]:
            for argument in [value, '--config='+value]:
                with self.subTest(argument=argument, cwd=cwd):
                    manifest = deepcopy(self.manifest)
                    manifest['inputs'] = [str(self.home/'external.txt')]
                    step = manifest['steps'][0]
                    step['argv'][1] = argument
                    if cwd is not None:
                        step['cwd'] = cwd
                    document, digest = normalize(manifest)
                    self.assertEqual(document['steps'][0]['argv'], step['argv'])
                    self.assertEqual(document['steps'][0]['cwd'], cwd or '{code}')
                    self.assertEqual(normalize(manifest), (document, digest))
                    self.assertEqual(digest, hashlib.sha256(canonical(document).encode()).hexdigest())
                    task, _ = self.store.submit(manifest)
                    self.assertEqual(task['digest'], digest)
                    self.assertFalse(task['internal']['approved_at'])

    def test_non_path_arguments_under_default_cwd_remain_usable(self):
        self.manifest['steps'][0]['argv'] = [
            '/usr/bin/python3', '-c', 'print("fixture")', '--name', 'plain-value',
        ]
        document, _ = normalize(self.manifest)
        self.assertEqual(document['steps'][0]['argv'], self.manifest['steps'][0]['argv'])

    def test_cli_validation_and_submission_reject_before_snapshot(self):
        manifest = self.home/'manifest.json'
        self.manifest['steps'][0].update(cwd='{project}/src', argv=['/usr/bin/python3', '--script=../src/train.py'])
        manifest.write_text(json.dumps(self.manifest))
        for action in ['validate', 'submit']:
            with patch('gpuqueue.cli.Store', return_value=self.store), redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, '运行代码请引用'):
                    cli.main([action, '--manifest', str(manifest)])
        self.assertFalse((self.store.root/'tasks').exists())
        self.manifest['steps'][0].update(cwd='{code}/src', argv=['/usr/bin/python3', '--script=../config.json'])
        manifest.write_text(json.dumps(self.manifest))
        for action in ['validate', 'submit']:
            output = io.StringIO()
            with patch('gpuqueue.cli.Store', return_value=self.store), redirect_stdout(output):
                cli.main([action, '--manifest', str(manifest)])
            self.assertTrue(json.loads(output.getvalue())['ok'])


class TracedStore(Store):
    def __init__(self, root):
        self.statements = []
        super().__init__(root)

    def connect(self):
        db = super().connect()
        db.set_trace_callback(self.statements.append)
        return db


class LocalControlFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = TracedStore(Path(temporary.name)/'queue')
        self.platform = Mock()
        self.platform.resources = {}
        self.service = Service({}, self.store, self.platform)

    def task(self):
        task_id, digest = 'GQ-fixture', 'a'*64
        with self.store.connect() as db:
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)', (
                task_id, digest, '{}', canonical({'id': task_id, 'state': 'ready', 'events': []}), '{}'))
        return task_id, digest

    def initialization_sql(self):
        return [sql for sql in self.store.statements if sql.upper().startswith((
            'CREATE TABLE', 'ALTER TABLE', 'PRAGMA TABLE_INFO', 'INSERT OR IGNORE INTO QUEUE_META'))]

class LocalControlTests(LocalControlFixture):
    def test_lazy_initialization_then_zero_ddl_across_cycles_claim_and_stop(self):
        self.assertIsNone(self.service._control)
        self.store.statements.clear()
        self.service.sync()
        self.assertEqual(len([sql for sql in self.initialization_sql() if sql.startswith('CREATE TABLE')]), 4)
        browser = Control(self.store)
        self.store.statements.clear()
        for _ in range(3):
            self.service.cycle()
        task_id, digest = self.task()
        state = browser.start(task_id, digest)
        self.service.sync()
        self.assertTrue(self.store.get(task_id)['internal']['approved_at'])
        self.service.remote('/api/worker/claim', {'id': task_id, 'digest': digest, 'revision': state['revision']})
        browser.stop(task_id, digest)
        self.service.sync()
        # Use the real process_stop confirmation branch with authoritative
        # resource closure; no platform submission or stop command is needed.
        task = self.store.get(task_id)
        task['internal']['request_uuid'] = 'original'
        task['internal']['argv'] = ['synthetic-runner']
        self.platform.resources = {'original': {'status': 'closed'}}
        self.service.process_stop(task)
        self.assertTrue(self.store.get(task_id)['internal']['stop_confirmed'])
        self.service.sync()
        self.assertEqual(self.initialization_sql(), [])
        self.platform.request.assert_not_called()
        self.platform.submit_job.assert_not_called()
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM queue_audit').fetchone()[0], 2)
        restarted = Service({}, self.store, self.platform)
        restarted.sync()
        self.assertIsNot(restarted.control, self.service.control)
        self.store.statements.clear()
        restarted.sync()
        self.assertEqual(self.initialization_sql(), [])
        self.assertTrue(restarted.control.state()['tasks'][0]['stopped_at'])

    def test_old_control_table_migrates_once_without_losing_authorization(self):
        task_id, digest = self.task()
        with self.store.connect() as db:
            db.execute('CREATE TABLE controls (id TEXT PRIMARY KEY, approved_at TEXT, claimed_at TEXT, position INTEGER NOT NULL DEFAULT 0)')
            db.execute('INSERT INTO controls VALUES (?,?,?,?)', (task_id, 'approved', None, 7))
        self.store.statements.clear()
        self.service.sync()
        self.assertEqual(len([s for s in self.initialization_sql() if s.startswith('ALTER TABLE')]), 2)
        self.assertEqual(self.store.get(task_id)['internal']['approved_at'], 'approved')
        self.assertEqual(self.store.get(task_id)['internal']['position'], 7)
        self.store.statements.clear()
        self.service.sync()
        self.assertEqual(self.initialization_sql(), [])
        self.assertEqual(self.service.control.state()['tasks'][0]['digest'], digest)

    def test_initialization_failure_is_reported_and_retried(self):
        initialize = Control
        attempts = []
        def constructor(store):
            attempts.append(store)
            if len(attempts) <= 2:
                raise sqlite3.OperationalError('synthetic init failure')
            return initialize(store)
        with patch('gpuqueue.service.Control', side_effect=constructor), redirect_stdout(io.StringIO()):
            self.service.cycle()
            self.assertIsNone(self.service._control)
            self.assertIn('synthetic init failure', self.service.error)
            self.service.cycle()
            self.assertIsNotNone(self.service._control)
            self.service.sync()
        self.assertEqual(len(attempts), 3)
        self.assertIsNone(self.service.error)


class StopMarkerTests(LocalControlFixture):
    def setUp(self):
        super().setUp()
        self.task_id, self.digest = self.task()
        self.browser = Control(self.store)
        state = self.browser.start(self.task_id, self.digest)
        self.browser.claim(self.task_id, self.digest, state['revision'])
        self.path = self.store.root/'tasks'/self.task_id/'run/stop.json'

    def stop(self):
        return self.browser.stop(self.task_id, self.digest)

    def assert_one_stop_audit(self):
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM queue_audit WHERE action LIKE 'browser_stop:%'").fetchone()[0], 1)

    def test_matching_pending_marker_has_no_writes_or_fsync_even_after_restart(self):
        with patch('gpuqueue.core.os.fsync', wraps=os.fsync) as fsync:
            self.stop()
        self.assertEqual(fsync.call_count, 1)
        expected = read_json(self.path)
        for service in [self.service, Service({}, Store(self.store.root), self.platform)]:
            with patch('gpuqueue.control.atomic_json', wraps=atomic_json) as write, \
                    patch('gpuqueue.core.os.fsync', wraps=os.fsync) as fsync:
                self.stop()
                service.sync()
                service.sync()
            write.assert_not_called()
            fsync.assert_not_called()
        self.assertEqual(read_json(self.path), expected)
        self.assertFalse(self.store.get(self.task_id)['internal'].get('stop_confirmed'))
        self.assert_one_stop_audit()

    def test_database_commit_survives_failed_marker_write_and_scheduler_repairs(self):
        with patch('gpuqueue.control.atomic_json', side_effect=OSError('synthetic interruption')):
            with self.assertRaisesRegex(OSError, 'synthetic interruption'):
                self.stop()
        shown = self.browser.state()['tasks'][0]
        self.assertTrue(shown['stop_requested_at'])
        self.assertFalse(self.path.exists())
        with patch('gpuqueue.core.os.fsync', wraps=os.fsync) as fsync:
            self.service.sync()
            self.service.sync()
        self.assertEqual(fsync.call_count, 1)
        self.assertEqual(read_json(self.path)['at'], shown['stop_requested_at'])
        self.assert_one_stop_audit()

    def test_missing_corrupt_and_mismatched_markers_are_repaired_once(self):
        self.stop()
        expected = read_json(self.path)
        variants = [None, b'{', b'\xff', b'[]', b'null'] + [
            json.dumps({**expected, key: 'wrong'}).encode() for key in expected]
        for repair in [self.stop, self.service.sync]:
            for contents in variants:
                with self.subTest(repair=repair.__name__, contents=contents):
                    if contents is None:
                        self.path.unlink()
                    else:
                        self.path.write_bytes(contents)
                    with patch('gpuqueue.core.os.fsync', wraps=os.fsync) as fsync:
                        repair()
                        repair()
                    self.assertEqual(fsync.call_count, 1)
                    self.assertEqual(read_json(self.path), expected)
        self.assert_one_stop_audit()

    def test_marker_permission_and_io_errors_are_not_hidden(self):
        self.stop()
        for error in [PermissionError('synthetic denied'), OSError('synthetic I/O')]:
            for repair in [self.stop, self.service.sync]:
                with self.subTest(error=error, repair=repair.__name__):
                    with patch('gpuqueue.control.read_json', side_effect=error):
                        with self.assertRaises(type(error)):
                            repair()
        self.assert_one_stop_audit()

    def test_confirmed_stop_with_stale_snapshot_does_not_rewrite_matching_marker(self):
        self.stop()
        self.browser.confirm_stop(self.task_id, self.digest)
        with patch('gpuqueue.core.os.fsync', wraps=os.fsync) as fsync:
            self.service.sync()
            self.service.sync()
        fsync.assert_not_called()
        # Preserve the stable terminal early exit, including no marker reads.
        with patch('gpuqueue.control.read_json', side_effect=AssertionError('terminal marker read')):
            self.stop()
            self.service.sync()
        self.assertTrue(self.store.get(self.task_id)['internal']['stop_confirmed'])
        self.assert_one_stop_audit()
