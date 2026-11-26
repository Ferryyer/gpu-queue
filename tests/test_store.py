"""SQLite transaction and connection lifetime guarantees."""
from pathlib import Path
import sqlite3
import tempfile
import unittest

from gpuqueue.core import Store


class StoreConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'state')

    def assert_closed(self, connection):
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')

    def test_success_commits_and_closes_connection(self):
        with self.store.connect() as connection:
            self.assertIsInstance(connection.execute('SELECT 1').fetchone(), sqlite3.Row)
            connection.execute('INSERT INTO meta VALUES (?, ?)', ('committed', 'true'))
        self.assert_closed(connection)
        self.assertTrue(self.store.metadata('committed'))

    def test_exception_rolls_back_and_closes_connection(self):
        with self.assertRaisesRegex(RuntimeError, 'abort transaction'):
            with self.store.connect() as connection:
                connection.execute('INSERT INTO meta VALUES (?, ?)', ('rolled_back', 'true'))
                raise RuntimeError('abort transaction')
        self.assert_closed(connection)
        self.assertIsNone(self.store.metadata('rolled_back'))
