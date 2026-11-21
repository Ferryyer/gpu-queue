import unittest
from unittest.mock import Mock, patch
from gpuqueue.host_monitor import HostMonitor


class HostMonitorTests(unittest.TestCase):
    def test_reuses_bundled_uid_sampler_and_caches_for_five_seconds(self):
        monitor = HostMonitor()
        monitor.module = Mock()
        monitor.module.render.return_value = '13 个线程\n2 个进程'
        with patch('gpuqueue.host_monitor.time.monotonic', return_value=10):
            first = monitor.state()
        with patch('gpuqueue.host_monitor.time.monotonic', return_value=14):
            self.assertIs(monitor.state(), first)
        self.assertEqual(monitor.module.render.call_count, 1)
        self.assertTrue(first['available'])
        self.assertEqual(first['text'], '13 个线程\n2 个进程')

    def test_read_failure_preserves_last_good_as_non_live(self):
        monitor = HostMonitor()
        monitor.module = Mock()
        monitor.module.render.return_value = '13 个线程'
        good = monitor.state()
        monitor.checked = float('-inf')
        monitor.module.render.side_effect = OSError('unreadable')
        failed = monitor.state()
        self.assertFalse(failed['available'])
        self.assertIsNone(failed['at'])
        self.assertEqual(failed['last_success'], good)
        monitor.checked = float('-inf')
        self.assertEqual(monitor.state()['last_success'], good)

    def test_absent_source_is_unavailable_instead_of_zero(self):
        monitor = HostMonitor()
        with patch('gpuqueue.host_monitor.HELPER', '/nonexistent/sampler.py'):
            result = monitor.state()
        self.assertFalse(result['available'])
        self.assertNotIn('0 个线程', result['text'])
