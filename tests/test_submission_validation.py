from concurrent.futures import ThreadPoolExecutor
import copy
import errno
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from gpuqueue.core import Store, atomic_json, normalize


class SubmissionValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        home_patch = patch('gpuqueue.core.HOME', self.home)
        home_patch.start()
        self.addCleanup(home_patch.stop)
        project = self.home / 'project'
        project.mkdir()
        (project / 'step.py').write_text('print("fixture")\n')
        self.manifest = {
            'title': 'submission fixture', 'project': str(project),
            'code_files': ['step.py'],
            'steps': [{'argv': [sys.executable, '{code}/step.py']}],
        }
        self.store = Store(self.home / 'state')

    def test_executable_must_be_a_literal_absolute_path(self):
        executable = self.home / 'python'
        executable.symlink_to(sys.executable)
        with patch.dict(os.environ, HOME=str(self.home)):
            self.assertTrue(Path('~/python').expanduser().is_file())
            for value in ('~/python', '~someone/python', 'python', '{home}/python'):
                with self.subTest(executable=value):
                    self.manifest['steps'][0]['argv'][0] = value
                    with self.assertRaisesRegex(ValueError, '绝对可执行路径'):
                        normalize(self.manifest)
        self.manifest['steps'][0]['argv'][0] = str(executable)
        doc, _ = normalize(self.manifest)
        self.assertEqual(doc['steps'][0]['argv'][0], str(executable))

    def test_string_fields_reject_non_strings_and_nul(self):
        for field in ('title', 'description', 'submission_key', 'name', 'cwd'):
            for value in (123, [], {}, None, False, 'bad\x00value'):
                with self.subTest(field=field, value=value):
                    manifest = copy.deepcopy(self.manifest)
                    target = manifest['steps'][0] if field in ('name', 'cwd') else manifest
                    target[field] = value
                    with self.assertRaisesRegex(ValueError, field):
                        normalize(manifest)

    def test_cwd_rejects_relative_empty_and_unknown_placeholder_paths(self):
        for value in ('', ' ', '.', 'relative/path', '~/project', '{unknown}/path', '{code}suffix'):
            with self.subTest(cwd=value):
                self.manifest['steps'][0]['cwd'] = value
                with self.assertRaisesRegex(ValueError, 'cwd'):
                    normalize(self.manifest)

    def test_valid_strings_and_directory_placeholders_are_preserved(self):
        self.manifest.update(title='  fixture  ', description='description', submission_key='v2')
        self.manifest['steps'][0]['name'] = 'step'
        for value in (str(self.home), '{code}', '{code}/subdir', '{outputs}', '{project}', '{home}/project'):
            with self.subTest(cwd=value):
                self.manifest['steps'][0]['cwd'] = value
                doc, _ = normalize(self.manifest)
                self.assertEqual(doc['title'], 'fixture')
                self.assertEqual(doc['description'], 'description')
                self.assertEqual(doc['submission_key'], 'v2')
                self.assertEqual(doc['steps'][0]['name'], 'step')
                self.assertEqual(doc['steps'][0]['cwd'], value)
        doc, _ = normalize({**self.manifest, 'steps': [{'argv': [sys.executable]}]})
        self.assertEqual(doc['steps'][0]['name'], '步骤 1')
        self.assertEqual(doc['steps'][0]['cwd'], '{code}')

    def orphan(self):
        task, _ = self.store.submit(self.manifest)
        with self.store.connect() as connection:
            connection.execute('DELETE FROM tasks WHERE id=?', (task['id'],))
        return task, self.store.root / 'tasks' / task['id']

    def snapshot(self, folder):
        return {str(p.relative_to(folder)): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                for p in folder.rglob('*') if p.is_file()}

    def assert_orphan_rejected(self, folder):
        before = self.snapshot(folder)
        self.assertEqual(self.store.tasks(), [])
        with self.assertRaisesRegex(ValueError, '拒绝复用残留产物'):
            self.store.submit(self.manifest)
        self.assertEqual(self.store.tasks(), [])
        self.assertEqual(self.snapshot(folder), before)
        self.assertEqual(list(folder.parent.glob('.prepare-*')), [])

    def test_orphan_with_run_results_is_rejected_for_both_collision_errnos(self):
        _, folder = self.orphan()
        atomic_json(folder / 'run/status.json', {'state': 'completed'})
        (folder / 'outputs/result.txt').write_text('previous result')
        for error in (errno.EEXIST, errno.ENOTEMPTY):
            with self.subTest(errno=error), patch.object(
                Path, 'rename', side_effect=OSError(error, os.strerror(error))
            ):
                self.assert_orphan_rejected(folder)

    def test_orphan_with_attempt_claim_is_rejected(self):
        _, folder = self.orphan()
        (folder / 'run/attempt.claim').touch()
        self.assert_orphan_rejected(folder)

    def test_orphan_requires_matching_digest_and_intact_manifest_document(self):
        task, folder = self.orphan()
        changed = {**task['doc'], 'description': 'different snapshot'}
        for plan in ({'digest': 'wrong', 'doc': task['doc']},
                     {'digest': task['digest'], 'doc': changed}, [], {}):
            with self.subTest(plan=plan):
                atomic_json(folder / 'manifest.json', plan)
                self.assert_orphan_rejected(folder)
        (folder / 'manifest.json').write_text('{invalid json')
        self.assert_orphan_rejected(folder)
        (folder / 'manifest.json').unlink()
        self.assert_orphan_rejected(folder)

    def test_orphan_requires_a_run_directory(self):
        _, folder = self.orphan()
        (folder / 'run').rmdir()
        self.assert_orphan_rejected(folder)
        (folder / 'run').write_text('not a directory')
        self.assert_orphan_rejected(folder)

    def test_matching_orphan_with_empty_run_is_recovered_unapproved(self):
        old, folder = self.orphan()
        before = self.snapshot(folder)
        task, created = self.store.submit(self.manifest)
        self.assertTrue(created)
        self.assertEqual(task['id'], old['id'])
        self.assertIsNone(task['internal']['approved_at'])
        self.assertEqual(list((folder / 'run').iterdir()), [])
        self.assertEqual(self.snapshot(folder), before)
        self.assertFalse(self.store.submit(self.manifest)[1])

    def test_concurrent_submission_before_winner_database_insert_is_idempotent(self):
        renamed, resume = threading.Event(), threading.Event()
        main_thread = threading.current_thread()
        rename = Path.rename

        def pause_winner(staging, folder):
            result = rename(staging, folder)
            if threading.current_thread() is not main_thread:
                renamed.set()
                if not resume.wait(10):
                    raise TimeoutError('competing submission did not finish')
            return result

        with patch.object(Path, 'rename', pause_winner), ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.store.submit, self.manifest)
            try:
                self.assertTrue(renamed.wait(10), 'snapshot did not reach rename barrier')
                self.assertEqual(self.store.tasks(), [])
                task, created = self.store.submit(self.manifest)
                self.assertTrue(created)
            finally:
                resume.set()
            duplicate, created = first.result(timeout=10)
        self.assertFalse(created)
        self.assertEqual(duplicate, task)
        self.assertEqual(self.store.tasks(), [task])
        self.assertIsNone(task['internal']['approved_at'])
        self.assertEqual(list((self.store.root / 'tasks').glob('.prepare-*')), [])


if __name__ == '__main__':
    unittest.main()
