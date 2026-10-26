import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('sync_app_version', ROOT / 'scripts/sync_app_version.py')
version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version)


class AppVersionTests(unittest.TestCase):
    def test_rejects_the_shipped_2001_ui_2004_bundle_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder)
            target = app / 'lib/data/res/build_data.dart'
            target.parent.mkdir(parents=True)
            (app / 'pubspec.yaml').write_text('version: 2.0.2004+2004\n')
            target.write_text('abstract class BuildData { static const int build = 2001; }\n')
            with self.assertRaisesRegex(ValueError, 'Dart/native build mismatch'):
                version.sync(app, check=True)
            version.sync(app)
            version.sync(app, check=True)
            self.assertIn('build = 2004;', target.read_text())
            (app / 'pubspec.yaml').write_text('version: 2.0.2005+2005\n')
            with self.assertRaises(ValueError):
                version.sync(app, check=True)
            version.sync(app)
            self.assertIn('build = 2005;', target.read_text())

    def test_checked_in_ui_version_matches_the_release(self):
        version.sync(ROOT / 'serverbox', check=True)

    def test_rejects_invalid_version_without_overwriting_build_data(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder)
            for invalid in ('version: 2.0.2005\n', 'version: 2.0.2005+0\n',
                            'version: 2.0.2004+2005\n', 'version: unknown\n'):
                (app / 'pubspec.yaml').write_text(invalid)
                with self.assertRaises(ValueError):
                    version.build_data(app)
