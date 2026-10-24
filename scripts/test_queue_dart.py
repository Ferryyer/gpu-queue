#!/usr/bin/env python3
"""Run production protocol/session tests without unrelated native build hooks."""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--flutter', default='flutter')
    args = parser.parse_args()
    build = ROOT/'build'
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='queue-dart-', dir=build) as folder:
        harness = Path(folder)
        (harness/'test').mkdir()
        (harness/'pubspec.yaml').write_text("name: queue_protocol_checks\nenvironment:\n  sdk: '>=3.11.0 <4.0.0'\ndependencies:\n  flutter:\n    sdk: flutter\ndev_dependencies:\n  flutter_test:\n    sdk: flutter\n")
        for name in ['queue_protocol_test.dart', 'queue_session_test.dart']:
            source = (ROOT/'serverbox/test/unit/app'/name).read_text()
            source = source.replace('package:server_box/', (ROOT/'serverbox/lib').as_uri()+'/')
            (harness/'test'/name).write_text(source)
        subprocess.run([args.flutter, 'test'], cwd=harness, check=True)

if __name__ == '__main__':
    main()
