#!/usr/bin/env python3
"""macOS integration checks for the shipped script and local date verifier."""
import os
import json
import hashlib
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
text(CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : "first", 240, 180, 24)
image.unlockFocus()
let rep = NSBitmapImageRep(data: image.tiffRepresentation!)!
try rep.representation(using: .jpeg, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
''')
        cls.generator = cls.root / 'fixture'
        subprocess.run(['xcrun', 'swiftc', str(fixture), '-o', str(cls.generator)], check=True)
        cls.image = cls.root / 'image.jpg'
        subprocess.run([str(cls.generator), str(cls.image)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.work.cleanup)
        self.cache = Path(self.work.name) / 'cache'

    def verify(self, date, image=None):
        return subprocess.run([str(self.checker), str(image or self.image), date], capture_output=True).returncode

    def run_script(self, fail=False, image=None):
        # Replace only the network executable, retaining production arguments,
        # control flow, validation, atomic writes and the real Vision helper.
        curl = Path(self.work.name) / 'curl'
        curl.write_text('#!/bin/bash\n' + ('exit 22\n' if fail else
            'while [[ "$1" != --output ]]; do shift; done\n/bin/cp "$CALENDAR_FIXTURE" "$2"\n'))
        curl.chmod(0o700)
        script = Path(self.work.name) / 'update.sh'
        script.write_text((ROOT/'scripts/update_daily_calendar.sh').read_text().replace('/usr/bin/curl', str(curl)))
        return subprocess.run(['/bin/bash', str(script), str(self.cache), '2026-10-29', str(self.checker)],
                              env={**os.environ, 'CALENDAR_FIXTURE': str(image or self.image)}, capture_output=True)

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
        manifest = json.loads((self.cache/'2026-10-29.json').read_text())
        image = self.cache / f'2026-10-29.{manifest["sha256"]}.jpg'
        original = image.stat().st_mtime_ns
        self.assertEqual(manifest['date'], '2026-10-29')
        self.assertEqual(manifest['sha256'], hashlib.sha256(image.read_bytes()).hexdigest())
        self.assertTrue(manifest['source'].startswith('https://img.owspace.com/'))
        # A valid cache is retained, but an offline check is not a success.
        self.assertEqual(self.run_script(fail=True).returncode, 75)
        self.assertEqual(image.stat().st_mtime_ns, original)
        self.assertEqual(list(self.cache.glob('.download.*')), [])

    def test_network_failure_keeps_previous_date(self):
        self.cache.mkdir()
        previous = self.cache / '2026-10-28.jpg'
        previous.write_bytes(self.image.read_bytes())
        self.assertEqual(self.run_script(fail=True).returncode, 75)
        self.assertTrue(previous.exists())
        self.assertFalse((self.cache/'2026-10-29.json').exists())
        self.assertEqual(list(self.cache.glob('.download.*')), [])

    def test_same_day_revision_replaces_cached_image_after_vision_check(self):
        self.assertEqual(self.run_script().returncode, 0)
        before = json.loads((self.cache/'2026-10-29.json').read_text())
        revised = Path(self.work.name)/'revision.jpg'
        subprocess.run([str(self.generator), str(revised), 'revision'], check=True)
        result = self.run_script(image=revised)
        self.assertEqual(result.returncode, 0, result.stderr)
        after = json.loads((self.cache/'2026-10-29.json').read_text())
        self.assertNotEqual(before['sha256'], after['sha256'])
        self.assertEqual(after['sha256'], hashlib.sha256(revised.read_bytes()).hexdigest())
        self.assertTrue((self.cache/f'2026-10-29.{before["sha256"]}.jpg').exists())

    def test_wrong_date_does_not_publish(self):
        # Our fixture is 29, so requesting 28 must reject both URL candidates.
        script = Path(self.work.name) / 'wrong.sh'
        self.run_script()
        script.write_text((Path(self.work.name)/'update.sh').read_text())
        result = subprocess.run(['/bin/bash', str(script), str(self.cache), '2026-10-28', str(self.checker)],
                                env={**os.environ, 'CALENDAR_FIXTURE': str(self.image)}, capture_output=True)
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertFalse((self.cache/'2026-10-28.json').exists())
        self.assertTrue((self.cache/'2026-10-29.json').exists())


if __name__ == '__main__':
    unittest.main()
