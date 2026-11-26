"""Malformed shared-runner files must not stop unrelated reconciliation."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from gpuqueue.control import Control
from gpuqueue.core import Store, atomic_json, canonical, read_json
from gpuqueue.platform import Markflow
from gpuqueue.service import Service


class SchedulerResilienceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.store = Store(self.home/'queue')
        self.control = Control(self.store)
        self.platform = Markflow(self.store, dict(home=str(self.home)))
        self.platform.check_auth = Mock()
        self.platform.lark = Mock(return_value=dict(messages=[]))
        self.platform.submit_job = Mock(return_value='synthetic-job')
        self.platform.request = Mock(return_value=None)
        self.service = Service({}, self.store, self.platform)

    def task(self, index, *, active=True):
        task_id = 'GQ-'+str(index).zfill(16)
        public = dict(id=task_id, name='synthetic task', state='ready', events=[])
        doc = dict(project=str(self.home), resources=dict(type='H卡离线', gpus=1, memory_gb=2))
        with self.store.connect() as db:
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',
                       (task_id, str(index)*64, canonical(doc), canonical(public), '{}'))
        folder = self.store.root/'tasks'/task_id
        (folder/'run').mkdir(parents=True)
        task = self.store.get(task_id)
        state = self.control.start(task_id, task['digest'])
        if active:
            self.control.claim(task_id, task['digest'], state['revision'])
            task['internal'].update(approved_at='browser', dispatch='submitted',
                                    request_uuid='synthetic-resource', job_uuid='compute-'+str(index))
            task['public']['state'] = 'running'
            self.store.save(task)
        return task, folder/'run/status.json'

    def completed(self, path):
        atomic_json(path, dict(state='completed', started_at=time.time()-10,
                               steps=[dict(state='completed', outputs=['kept-output'])]))

    def stop(self, task, *, proof=True):
        self.control.stop(task['id'], task['digest'])
        self.service.sync()
        task = self.store.get(task['id'])
        if proof:
            atomic_json(self.store.root/'tasks'/task['id']/'run/stop-result.json', dict(
                state='stopped', mode='legacy', task=task['id'], digest=task['digest'],
                stop_at=task['internal']['stop_requested_at'], uid=os.getuid(),
                request=task['internal']['request_uuid'], job=task['internal']['job_uuid']))

    def test_bad_active_status_does_not_block_other_completion_or_stop(self):
        corrupt, path = self.task(1)
        finished, good_path = self.task(2)
        stopping, _ = self.task(3)
        self.completed(good_path)
        self.stop(stopping)
        path.write_text('{"state":"running",')
        original = path.read_bytes()
        for _ in range(2):
            self.service = Service({}, self.store, self.platform)
            self.service.tick()
            saved = self.store.get(corrupt['id'])
            self.assertEqual(saved['public']['state'], 'execution_unknown')
            self.assertIn('状态文件不可读', saved['public']['failureReason'])
            self.assertEqual(saved['internal']['job_uuid'], corrupt['internal']['job_uuid'])
            self.assertEqual(saved['internal']['dispatch'], 'submitted')
            self.assertFalse(saved['internal'].get('terminal_reconciled'))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(self.store.get(finished['id'])['public']['state'], 'completed')
            self.assertEqual(self.store.get(stopping['id'])['public']['state'], 'stopped')
        self.assertEqual(len(saved['public']['events']), 1)
        self.platform.submit_job.assert_not_called()
        self.platform.request.assert_not_called()
        self.completed(path)
        self.service.tick()
        saved = self.store.get(corrupt['id'])
        self.assertEqual(saved['public']['state'], 'completed')
        self.assertNotIn('result_refresh_error', saved['public'])
        self.assertNotIn('failureReason', saved['public'])

    def test_corrupt_status_during_stop_does_not_hide_matching_stop_proof(self):
        task, path = self.task(1)
        self.stop(task)
        path.write_text('{truncated')
        self.service.tick()
        saved = self.store.get(task['id'])
        self.assertEqual(saved['public']['state'], 'stopped')
        self.assertTrue(saved['internal']['stop_confirmed'])
        self.assertEqual(path.read_text(), '{truncated')
        self.platform.submit_job.assert_not_called()

    def test_unreadable_or_nonobject_status_stays_pending_until_valid_heartbeat(self):
        task, path = self.task(1)
        for content in ['null', '[]', '{}', '{truncated']:
            with self.subTest(content=content):
                path.write_text(content)
                self.service.tick()
                self.assertEqual(self.store.get(task['id'])['public']['state'], 'execution_unknown')
                self.assertEqual(path.read_text(), content)
        original_read = read_json
        def denied(file, *args):
            if Path(file) == path:
                raise PermissionError('synthetic read failure')
            return original_read(file, *args)
        with patch('gpuqueue.service.read_json', side_effect=denied):
            self.service.tick()
        atomic_json(path, dict(state='running', started_at=time.time()-10,
                               updated_at=time.time(), steps=[]))
        self.service.tick()
        saved = self.store.get(task['id'])
        self.assertEqual(saved['public']['state'], 'running')
        self.assertNotIn('failureReason', saved['public'])
        self.platform.submit_job.assert_not_called()

    def test_corruption_on_second_read_cannot_be_guessed_as_completion(self):
        task, path = self.task(1)
        self.completed(path)
        atomic_json(self.platform.job_folder('synthetic-resource')/'compute-1/status.json',
                    dict(state='finished', exit_code=0))
        original_read = read_json
        reads = []
        def truncated_on_reread(file, *args):
            if Path(file) == path:
                reads.append(file)
                if len(reads) == 2:
                    path.write_text('{truncated')
            return original_read(file, *args)
        with patch('gpuqueue.service.read_json', side_effect=truncated_on_reread):
            self.service.tick()
        saved = self.store.get(task['id'])
        self.assertEqual(saved['public']['state'], 'execution_unknown')
        self.assertFalse(saved['internal'].get('finished_recorded'))
        self.platform.submit_job.assert_not_called()


if __name__ == '__main__':
    unittest.main()
