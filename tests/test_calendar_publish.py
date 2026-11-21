import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('publish_calendar_notes', ROOT/'scripts/publish_calendar_notes.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class CalendarPublishTests(unittest.TestCase):
    def test_requires_exact_day_and_reviewed_public_content(self):
        note = '<!-- inspire-calendar-date: 2026-10-29 -->\n# 出处\n置信度：高\n[来源](https://example.com/book)\n'
        self.assertEqual(publisher.validate(note, '2026-10-29'), note)
        for bad in [note.replace('2026-10-29', '2026-10-28'), note+'<script>x</script>',
                    note+'![x](https://example.com/image)', note+'-----BEGIN OPENSSH PRIVATE KEY-----',
                    note+'/Users/private/info', note+'x'*65536]:
            with self.assertRaises(ValueError):
                publisher.validate(bad, '2026-10-29')
