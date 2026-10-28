import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from gpuqueue.core import Store, canonical
from gpuqueue.control import Control, ControlError
from gpuqueue.service import Service


class TaskDeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'queue')
        self.control = Control(self.store)
        self.ids = ['GQ-' + str(i).zfill(16) for i in range(1, 4)]
        for i, task_id in enumerate(self.ids):
            public = {'id': task_id, 'name': 'fixture', 'state': 'ready', 'events': []}
            with self.store.connect() as db:
                db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',
                           (task_id, str(i)*64, '{}', canonical(public), '{}'))

    def tearDown(self):
        self.temp.cleanup()

    def state(self, index, state, **internal):
        task = self.store.get(self.ids[index])
        task['public']['state'] = state
        task['internal'].update(internal)
        self.store.save(task)

    def test_delete_is_version_bound_persistent_and_idempotent(self):
        self.state(0, 'completed')
        with self.assertRaises(ControlError): self.control.delete(self.ids[0], 'wrong')
        result = self.control.delete(self.ids[0], '0'*64)
        self.assertNotIn(self.ids[0], [t['id'] for t in result['tasks']])
        self.assertEqual(Control(self.store).state(), result)
        self.assertEqual(self.control.delete(self.ids[0], '0'*64), result)
        with self.assertRaises(ControlError): self.control.start(self.ids[0], '0'*64)
        self.assertIsNotNone(self.store.get(self.ids[0]))
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM queue_audit WHERE action LIKE 'delete_record:%'").fetchone()[0], 1)

    def test_pending_running_and_unconfirmed_execution_are_protected(self):
        for state in ['queued', 'waiting_gpu', 'running', 'dispatching', 'stopping', 'execution_unknown', 'blocked']:
            self.state(0, state)
            with self.subTest(state=state), self.assertRaises(ControlError):
                self.control.delete(self.ids[0], '0'*64)
        for dispatch in ['submitting', 'unknown']:
            self.state(0, 'failed', dispatch=dispatch)
            with self.subTest(dispatch=dispatch), self.assertRaises(ControlError):
                self.control.delete(self.ids[0], '0'*64)
        self.assertEqual(len(self.control.state()['tasks']), 3)

    def test_cleanup_only_removes_the_confirmed_completed_and_cancelled_ids(self):
        self.state(0, 'completed')
        self.state(1, 'cancelled')
        before = self.control.state()
        self.state(2, 'completed')  # Finished after the user opened the dialog.
        result = self.control.cleanup(self.ids[:2], before['revision'])
        self.assertEqual([t['id'] for t in result['tasks']], self.ids[2:])

    def test_cleanup_is_atomic_when_one_task_changes_state(self):
        self.state(0, 'completed')
        self.state(1, 'cancelled')
        before = self.control.state()
        self.state(1, 'running')
        with self.assertRaises(ControlError): self.control.cleanup(self.ids[:2], before['revision'])
        self.assertEqual(len(self.control.state()['tasks']), 3)
        self.assertEqual(self.control.state()['revision'], before['revision'])

    def test_stale_or_malformed_cleanup_cannot_delete(self):
        self.state(0, 'completed')
        for ids, revision in [([self.ids[0]], -1), ([], 0), ([self.ids[0]]*2, 0), ([None], 0), ([self.ids[0]], True)]:
            with self.subTest(ids=ids), self.assertRaises(ControlError):
                self.control.cleanup(ids, revision)
        self.assertEqual(len(self.control.state()['tasks']), 3)

    def test_deletion_preserves_project_files_logs_and_outputs(self):
        self.state(0, 'completed')
        paths = [self.root / 'project' / 'source.py', self.store.root / 'tasks' / self.ids[0] / 'run' / 'output.log']
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('keep this')
        self.control.delete(self.ids[0], '0'*64)
        self.assertTrue(all(path.read_text() == 'keep this' for path in paths))

    def test_cancel_then_delete_before_scheduler_sync_never_resumes_the_job(self):
        platform = Mock(); platform.resources = {}
        service = Service({}, self.store, platform)
        self.control.start(self.ids[0], '0'*64)
        service.sync()  # Local scheduler knows the old queued authorization.
        self.control.stop(self.ids[0], '0'*64)
        self.control.delete(self.ids[0], '0'*64)
        service.tick()
        self.assertEqual(self.store.get(self.ids[0])['public']['state'], 'cancelled')
        platform.request.assert_not_called()
        platform.submit_job.assert_not_called()
        self.assertNotIn(self.ids[0], [t['id'] for t in self.control.state()['tasks']])

    def test_unapproved_ready_record_can_be_deleted_without_authorizing_it(self):
        self.control.delete(self.ids[0], '0'*64)
        with self.assertRaises(ControlError): self.control.claim(self.ids[0], '0'*64, self.control.state()['revision'])
        self.assertFalse(self.store.get(self.ids[0])['internal'].get('approved_at'))


if __name__ == '__main__':
    unittest.main()
