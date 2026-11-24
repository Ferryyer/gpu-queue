#!/usr/bin/env python3
"""macOS integration checks for the shipped script and local date verifier."""
import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(os.uname().sysname == 'Darwin', 'requires Apple Vision')
class CalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='inspire-calendar-native-')
        cls.root = Path(cls.temp.name)
        cls.checker = cls.root / 'CalendarCheck'
        subprocess.run(['xcrun', 'swiftc', '-swift-version', '5',
                        str(ROOT/'serverbox/macos/CalendarCheck/main.swift'), '-o', str(cls.checker)], check=True)
        fixture = cls.root / 'fixture.swift'
        fixture.write_text('''import AppKit
let image = NSImage(size: NSSize(width: 600, height: 900))
image.lockFocus()
NSColor.white.setFill()
NSRect(x: 0, y: 0, width: 600, height: 900).fill()
func text(_ value: String, _ x: CGFloat, _ y: CGFloat, _ size: CGFloat) {
    (value as NSString).draw(at: NSPoint(x: x, y: y), withAttributes: [
        .font: NSFont.systemFont(ofSize: size), .foregroundColor: NSColor.black])
}
text("十月", 240, 840, 28)
text("29", 90, 360, 320)
text("单向历2026", 420, 20, 24)
if CommandLine.arguments.count > 2 { text(CommandLine.arguments[2], 40, 160, 24) }
image.unlockFocus()
let rep = NSBitmapImageRep(data: image.tiffRepresentation!)!
try rep.representation(using: .jpeg, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
''')
        generator = cls.root / 'fixture'
        subprocess.run(['xcrun', 'swiftc', str(fixture), '-o', str(generator)], check=True)
        cls.image = cls.root / 'image.jpg'
        subprocess.run([str(generator), str(cls.image)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.work.cleanup)
        self.cache = Path(self.work.name) / 'cache'

    def verify(self, date, image=None):
        return subprocess.run([str(self.checker), str(image or self.image), date], capture_output=True).returncode

    def run_script(self, fail=False):
        # Replace only the network executable, retaining production arguments,
        # control flow, validation, atomic writes and the real Vision helper.
        curl = Path(self.work.name) / 'curl'
        curl.write_text('#!/bin/bash\n' + ('exit 22\n' if fail else
            'while [[ "$1" != --output ]]; do shift; done\n/bin/cp "$CALENDAR_FIXTURE" "$2"\n'))
        curl.chmod(0o700)
        script = Path(self.work.name) / 'update.sh'
        script.write_text((ROOT/'scripts/update_daily_calendar.sh').read_text().replace('/usr/bin/curl', str(curl)))
        return subprocess.run(['/bin/bash', str(script), str(self.cache), '2026-10-29', str(self.checker)],
                              env={**os.environ, 'CALENDAR_FIXTURE': str(self.image)}, capture_output=True)

    def test_printed_date_is_required(self):
        self.assertEqual(self.verify('2026-10-29'), 0)
        for day in ['2026-10-28', '2026-11-29', '2027-10-29']:
            self.assertNotEqual(self.verify(day), 0)
        invalid = Path(self.work.name) / 'html.jpg'
        invalid.write_text('<html>2026-10-29</html>')
        self.assertNotEqual(self.verify('2026-10-29', invalid), 0)

    def test_first_run_and_offline_cache(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        image = self.cache / (self.cache/'2026-10-29.current').read_text().strip() / 'image.jpg'
        original = image.stat().st_mtime_ns
        self.assertIn('2026-10-29', (image.parent/'source.md').read_text())
        self.assertEqual(self.run_script(fail=True).returncode, 75)
        self.assertEqual(image.stat().st_mtime_ns, original)
        self.assertEqual(list(self.cache.glob('.download.*')), [])

    def test_network_failure_keeps_previous_date(self):
        self.cache.mkdir()
        previous = self.cache / '2026-10-28.jpg'
        previous.write_bytes(self.image.read_bytes())
        self.assertEqual(self.run_script(fail=True).returncode, 75)
        self.assertTrue(previous.exists())
        self.assertFalse((self.cache/'2026-10-29.current').exists())
        self.assertEqual(list(self.cache.glob('.download.*')), [])

    def test_same_day_revision_is_revalidated(self):
        self.assertEqual(self.run_script().returncode, 0)
        old = (self.cache/'2026-10-29.current').read_text()
        revised = Path(self.work.name)/'revised.jpg'
        subprocess.run([str(self.root/'fixture'), str(revised), 'Revised content'], check=True)
        self.image = revised
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual((self.cache/'2026-10-29.current').read_text(), old)
        current = self.cache/(self.cache/'2026-10-29.current').read_text().strip()
        self.assertEqual((current/'image.jpg').read_bytes(), revised.read_bytes())

    def test_wrong_date_does_not_publish(self):
        # Our fixture is 29, so requesting 28 must reject both URL candidates.
        script = Path(self.work.name) / 'wrong.sh'
        self.run_script()
        script.write_text((Path(self.work.name)/'update.sh').read_text())
        result = subprocess.run(['/bin/bash', str(script), str(self.cache), '2026-10-28', str(self.checker)],
                                env={**os.environ, 'CALENDAR_FIXTURE': str(self.image)}, capture_output=True)
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertFalse((self.cache/'2026-10-28.current').exists())
        self.assertTrue((self.cache/'2026-10-29.current').exists())


class ScriptProtocolTests(unittest.TestCase):
    """Run real shell control flow on CPU; only OS/network/OCR boundaries fake.

    These tests do not claim to exercise Apple Vision. CalendarTests above does.
    No network requests or personal cache are used.
    """
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='calendar-script-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root/'cache'
        self.responses = self.root/'responses.json'
        self.log = self.root/'requests.jsonl'
        self.responses.write_text('{}')
        self.env = {**os.environ, 'RESPONSES': str(self.responses), 'REQUEST_LOG': str(self.log)}
        helpers = {
            'date': '''import datetime, sys
args = sys.argv[1:]
day = args[args.index('-f') + 2]
value = datetime.date.fromisoformat(day)
if '-v+1d' in args: value += datetime.timedelta(days=1)
print(value.isoformat())
''',
            'stat': '''import os, sys
print(os.stat(sys.argv[-1]).st_size)
''',
            'curl': '''import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['REQUEST_LOG'], 'a') as stream: stream.write(json.dumps(args) + '\\n')
value = json.loads(pathlib.Path(os.environ['RESPONSES']).read_text()).get(args[-1].split('?')[0])
if value is None: sys.exit(22)
pathlib.Path(args[args.index('--output') + 1]).write_text(value)
''',
            'checker': '''import pathlib, sys
content = pathlib.Path(sys.argv[1]).read_text()
sys.exit(0 if content.startswith('printed:' + sys.argv[2] + '\\n') else 66)
''',
        }
        # Absolute interpreter survives the script's deliberately restricted PATH.
        import sys
        script = (ROOT/'scripts/update_daily_calendar.sh').read_text()
        for name, body in helpers.items():
            helper = self.root/name
            helper.write_text(f'#!{sys.executable}\n' + body)
            helper.chmod(0o700)
            script = script.replace('/bin/date' if name == 'date' else f'/usr/bin/{name}', str(helper))
        self.script = self.root/'update.sh'
        self.script.write_text(script)

    def run_script(self, day='2026-10-29'):
        return subprocess.run(['/bin/bash', str(self.script), str(self.cache), day, str(self.root/'checker')],
                              env=self.env, capture_output=True)

    def publish(self, day='2026-10-29', version='one', candidate='1029', printed=None):
        self.responses.write_text(json.dumps({
            f'https://img.owspace.com/Public/uploads/Download/2026/{candidate}.jpg':
                f'printed:{printed or day}\n{version}'}))
        return self.run_script(day)

    def current(self, day='2026-10-29'):
        return self.cache/(self.cache/f'{day}.current').read_text().strip()

    def test_every_call_revalidates_today_and_publishes_same_day_revision(self):
        first = self.publish()
        self.assertEqual(first.returncode, 0, first.stderr)
        old = self.current()
        result = self.publish(version='revised', candidate='1030')
        self.assertEqual(result.returncode, 0, result.stderr)
        new = self.current()
        self.assertNotEqual(old, new)
        self.assertIn('revised', (new/'image.jpg').read_text())
        self.assertIn('/1030.jpg', (new/'source.md').read_text())
        self.assertIn('one', (old/'image.jpg').read_text())
        self.assertEqual(list(self.cache.glob('.download.*')), [])
        self.assertFalse((self.cache/'.update-lock').exists())

    def test_same_image_is_still_downloaded_but_retains_revision_and_notes(self):
        self.assertEqual(self.publish().returncode, 0)
        current = self.current()
        (current/'notes.md').write_text('existing editorial notes')
        self.assertEqual(self.publish().returncode, 0)
        self.assertEqual(self.current(), current)
        self.assertTrue((current/'notes.md').exists())
        requests = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(len(requests), 2)
        for args in requests:
            self.assertIn('Cache-Control: no-cache', args)
            self.assertIn('=https', args)
            self.assertNotIn('--insecure', args)
            self.assertIn('?inspire_refresh=', args[-1])
        self.assertNotEqual(requests[0][-1], requests[1][-1])

    def test_offline_today_is_not_reported_as_success_and_can_retry(self):
        self.assertEqual(self.publish().returncode, 0)
        old = self.current()
        self.responses.write_text('{}')
        self.assertEqual(self.run_script().returncode, 75)
        self.assertEqual(self.current(), old)
        self.assertEqual(self.publish(version='recovered').returncode, 0)
        self.assertIn('recovered', (self.current()/'image.jpg').read_text())

    def test_wrong_printed_date_cannot_replace_cached_image_or_source(self):
        self.assertEqual(self.publish().returncode, 0)
        old = self.current()
        self.assertEqual(self.publish(printed='2026-10-28', version='invalid').returncode, 75)
        self.assertEqual(self.current(), old)
        self.assertIn('/1029.jpg', (old/'source.md').read_text())
        self.responses.write_text(json.dumps({
            'https://img.owspace.com/Public/uploads/Download/2026/1029.jpg': '<html>error</html>'}))
        self.assertEqual(self.run_script().returncode, 75)
        self.assertEqual(self.current(), old)

    def test_previous_day_and_legacy_cache_survive_failed_update(self):
        self.cache.mkdir()
        previous = self.cache/'2026-10-28.jpg'
        previous.write_text('legacy image')
        self.assertEqual(self.run_script().returncode, 75)
        self.assertEqual(previous.read_text(), 'legacy image')
        self.assertFalse((self.cache/'2026-10-29.current').exists())

    def test_failed_pointer_commit_preserves_entire_previous_revision(self):
        self.assertEqual(self.publish().returncode, 0)
        old = self.current()
        # Inject a filesystem failure at the sole publication operation.
        script = self.script.read_text().replace(
            '/bin/mv -f "$temp/current" "$cache/$day.current"', '/bin/false')
        self.script.write_text(script)
        self.assertNotEqual(self.publish(version='uncommitted').returncode, 0)
        self.assertEqual(self.current(), old)
        self.assertIn('one', (old/'image.jpg').read_text())
        self.assertIn('/1029.jpg', (old/'source.md').read_text())
        self.assertEqual(len(list(self.cache.glob('snapshot-*'))), 1)
        self.assertEqual(list(self.cache.glob('.download.*')), [])



if __name__ == '__main__':
    unittest.main()
