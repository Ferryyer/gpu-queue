import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('package_unified_macos',Path(__file__).resolve().parent.parent/'scripts/package_unified_macos.py')
package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)

class UnifiedPackageTests(unittest.TestCase):
    def test_bundle_version_and_executable_are_required(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Path(folder)/'GPU Queue 测试.app';contents=app/'Contents';(contents/'MacOS').mkdir(parents=True)
            executable=contents/'MacOS/GPU Queue';executable.write_bytes(b'CPU test fixture, not a Mac binary')
            info={'CFBundleVersion':package.BUILD,'CFBundleShortVersionString':package.MARKETING,'CFBundleIdentifier':'local.fixture.gpuq','CFBundleExecutable':'GPU Queue'}
            (contents/'Info.plist').write_bytes(plistlib.dumps(info))
            self.assertEqual(package.inspect_app(app)['build'],2000)
            info['CFBundleVersion']='1816';(contents/'Info.plist').write_bytes(plistlib.dumps(info))
            with self.assertRaises(ValueError):package.inspect_app(app)
            info['CFBundleVersion']=package.BUILD;info['CFBundleExecutable']='../outside';(contents/'Info.plist').write_bytes(plistlib.dumps(info))
            with self.assertRaises(ValueError):package.inspect_app(app)
