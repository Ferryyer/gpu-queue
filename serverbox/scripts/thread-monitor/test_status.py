import os
from pathlib import Path
import tempfile
import unittest

import status


class ThreadStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.proc = self.root / 'proc'
        self.proc.mkdir()
        self.uid = os.getuid()

    def process(self, pid, name, threads, uid=None, limits='512 512'):
        path = self.proc / str(pid)
        path.mkdir()
        (path / 'status').write_text(f'Name:\t{name}\nUid:\t{self.uid if uid is None else uid}\t0\t0\t0\nThreads:\t{threads}\n')
        (path / 'limits').write_text(f'Max processes             {limits}                processes\n')
        return path

    def test_real_uid_filter_and_threads_not_process_count(self):
        self.process(101, 'codex', 24)
        self.process(102, 'codex', 17)
        self.process(103, 'foreign', 999, self.uid + 1)
        rows, skipped, timed_out = status.sample(self.proc, self.uid)
        self.assertEqual(sum(row[2] for row in rows), 41)
        self.assertEqual(len(rows), 2)
        self.assertEqual(skipped, 0)
        self.assertFalse(timed_out)

    def test_disappeared_and_invalid_process_do_not_zero_other_counts(self):
        self.process(101, 'codex', 24)
        self.process(102, 'exiting', 0)
        (self.proc / '103').mkdir()
        rows, skipped, _ = status.sample(self.proc, self.uid)
        self.assertEqual(rows, [(101, 'codex', 24)])
        self.assertEqual(skipped, 2)

    def test_deadline_marks_partial_sample(self):
        self.process(101, 'codex', 24)
        rows, _, timed_out = status.sample(self.proc, self.uid, deadline=0)
        self.assertEqual(rows, [])
        self.assertTrue(timed_out)

    def test_limits_are_owned_and_source_specific(self):
        self.process(101, 'supervisor', 1)
        self.process('self', 'sampler', 1, limits='unlimited unlimited')
        state = self.root / '.local/state/markflow-services'
        state.mkdir(parents=True)
        (state / 'status.json').write_text('{"supervisor_pid":101}')
        output = status.render(self.proc, self.root, self.uid, 'linlishuo')
        self.assertIn('本次采集：无限制/无限制', output)
        self.assertIn('服务监管器 PID 101：512/512', output)
        self.assertIn('非 CPU/带宽', output)
        self.process(102, 'foreign', 1, self.uid + 1)
        self.assertEqual(status.nproc_limit(self.proc / '102', self.uid), '不可读')

    def test_programs_are_ranked_and_grouped_without_command_lines(self):
        self.process(101, 'codex', 24)
        self.process(102, 'codex', 17)
        self.process(103, 'paseo', 5)
        self.process('self', 'sampler', 1)
        output = status.render(self.proc, self.root, self.uid, 'linlishuo')
        self.assertEqual(output.splitlines()[0], '46 个线程')
        self.assertTrue(output.splitlines()[1].startswith('3 个进程 · linlishuo'))
        self.assertIn('codex: 41 / 2 · 最大 PID 101 (24)', output)
        self.assertLess(output.index('codex:'), output.index('paseo:'))
        self.assertIn('服务监管器：未取得 PID', output)

    def test_unreadable_proc_is_unavailable(self):
        with self.assertRaises(OSError):
            status.render(self.root / 'missing', self.root, self.uid, 'linlishuo')


if __name__ == '__main__':
    unittest.main()
