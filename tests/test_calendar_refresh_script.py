"""Portable script transaction checks with synthetic, isolated platform tools.

These test download/control flow, not Vision OCR. The real Apple verifier is
exercised separately by scripts/test_daily_calendar.py on macOS.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CalendarRefreshScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='calendar-script-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / 'cache'
        self.responses = self.root / 'responses.json'
        self.calls = self.root / 'calls.jsonl'
        self.date = self.tool('date', '''
import datetime, sys
args = sys.argv[1:]
value = args[args.index('-f') + 2]
day = datetime.datetime.strptime(value, '%Y-%m-%d')
if '-v+1d' in args: day += datetime.timedelta(days=1)
print(day.strftime('%Y-%m-%d'))
''')
        self.stat = self.tool('stat', '''
import os, sys
print(os.stat(sys.argv[-1]).st_size)
''')
        self.curl = self.tool('curl', '''
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['CALENDAR_TEST_CALLS'], 'a') as stream:
    stream.write(json.dumps(args) + '\\n')
value = json.loads(pathlib.Path(os.environ['CALENDAR_TEST_RESPONSES']).read_text()).get(args[-1].split('?')[0])
if value is None: sys.exit(22)
pathlib.Path(args[args.index('--output') + 1]).write_bytes(value.encode())
''')
        self.checker = self.tool('checker', '''
import pathlib, sys
content = pathlib.Path(sys.argv[1]).read_bytes()
sys.exit(0 if content.startswith(('SYNTHETIC_CALENDAR ' + sys.argv[2] + ' ').encode()) else 66)
''')
        source = (ROOT/'scripts/update_daily_calendar.sh').read_text()
        for original, replacement in [('/bin/date', self.date), ('/usr/bin/stat', self.stat), ('/usr/bin/curl', self.curl)]:
            source = source.replace(original, str(replacement))
        self.script = self.root / 'update.sh'
        self.script.write_text(source)

    def tool(self, name, content):
        path = self.root / name
        path.write_text(f'#!{sys.executable}\n' + content)
        path.chmod(0o700)
        return path

    def run_script(self, responses):
        self.responses.write_text(json.dumps(responses))
        return subprocess.run(['/bin/bash', str(self.script), str(self.cache), '2026-10-29', str(self.checker)],
            env={**os.environ, 'CALENDAR_TEST_CALLS': str(self.calls), 'CALENDAR_TEST_RESPONSES': str(self.responses)},
            capture_output=True)

    @staticmethod
    def url(day):
        return f'https://img.owspace.com/Public/uploads/Download/2026/10{day}.jpg'

    def snapshot(self):
        manifest = json.loads((self.cache/'2026-10-29.json').read_text())
        image = (self.cache/f'2026-10-29.{manifest["sha256"]}.jpg').read_bytes()
        self.assertEqual(hashlib.sha256(image).hexdigest(), manifest['sha256'])
        self.assertEqual(manifest['date'], '2026-10-29')
        return manifest, image

    def test_same_day_rechecks_upstream_and_commits_revision_and_matching_source(self):
        first = 'SYNTHETIC_CALENDAR 2026-10-29 first'
        second = 'SYNTHETIC_CALENDAR 2026-10-29 revision'
        self.assertEqual(self.run_script({self.url('29'): first}).returncode, 0)
        old, old_image = self.snapshot()
        # First candidate has a wrong printed date; second candidate is today's revision.
        result = self.run_script({self.url('29'): 'SYNTHETIC_CALENDAR 2026-10-28 old', self.url('30'): second})
        self.assertEqual(result.returncode, 0, result.stderr)
        current, image = self.snapshot()
        self.assertEqual(image.decode(), second)
        self.assertEqual(current['source'], self.url('30'))
        self.assertNotEqual(old['sha256'], current['sha256'])
        self.assertEqual((self.cache/f'2026-10-29.{old["sha256"]}.jpg').read_bytes(), old_image)
        for args in map(json.loads, self.calls.read_text().splitlines()):
            self.assertIn('Cache-Control: no-cache', args)
            self.assertEqual(args[args.index('--proto') + 1], '=https')
            self.assertEqual(args[args.index('--proto-redir') + 1], '=https')
            self.assertNotIn('--insecure', args)
            self.assertIn('?inspire_calendar_check=', args[-1])
        self.assertEqual(list(self.cache.glob('.download.*')), [])

    def test_offline_and_invalid_image_preserve_manifest_and_report_failure(self):
        self.assertEqual(self.run_script({self.url('29'): 'SYNTHETIC_CALENDAR 2026-10-29 good'}).returncode, 0)
        before = self.snapshot()
        for responses in [{}, {self.url('29'): '<html>2026-10-29</html>'},
                          {self.url('29'): 'SYNTHETIC_CALENDAR 2026-10-28 wrong'}]:
            self.assertEqual(self.run_script(responses).returncode, 75)
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(list(self.cache.glob('.download.*')), [])

    def test_legacy_today_cache_does_not_short_circuit_network_or_fake_success(self):
        self.cache.mkdir()
        legacy = self.cache/'2026-10-29.jpg'
        legacy.write_text('SYNTHETIC_CALENDAR 2026-10-29 legacy')
        self.assertEqual(self.run_script({}).returncode, 75)
        self.assertTrue(legacy.exists())
        self.assertEqual(len(self.calls.read_text().splitlines()), 2)
        self.assertFalse((self.cache/'2026-10-29.json').exists())


if __name__ == '__main__':
    unittest.main()
