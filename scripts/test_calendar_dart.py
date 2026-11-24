#!/usr/bin/env python3
"""Run real calendar core tests without unrelated application native hooks.

Use --flutter /path/to/flutter to also exercise the production panel on the
CPU Flutter test engine. The default only needs the Dart SDK.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dart', default='dart')
    parser.add_argument('--flutter')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    build = ROOT/'build'
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='calendar-dart-', dir=build) as folder:
        harness = Path(folder)
        (harness/'test').mkdir()
        spec = "name: calendar_checks\nenvironment:\n  sdk: '>=3.11.0 <4.0.0'\ndev_dependencies:\n  test: ^1.29.0\n"
        names = ['local_calendar_test.dart']
        if args.flutter:
            spec += ('  flutter_test:\n    sdk: flutter\ndependencies:\n'
                     '  flutter:\n    sdk: flutter\n  material_ui: 1.5.0\n'
                     '  flutter_markdown_plus: ^1.0.12\n  url_launcher: ^6.2.6\n'
                     'flutter:\n  uses-material-design: true\n')
            names.append('daily_calendar_widget_test.dart')
        (harness/'pubspec.yaml').write_text(spec)
        for name in names:
            (harness/'test'/name).write_text((ROOT/'serverbox/test/unit/app'/name).read_text())
        sdk = args.flutter or args.dart
        subprocess.run([sdk, 'pub', 'get', *(['--offline'] if args.offline else [])], cwd=harness, check=True)
        config = harness/'.dart_tool/package_config.json'
        packages = json.loads(config.read_text())
        packages['packages'].append({'name': 'server_box', 'rootUri': (ROOT/'serverbox').as_uri(),
                                    'packageUri': 'lib/', 'languageVersion': '3.11'})
        config.write_text(json.dumps(packages))
        subprocess.run([sdk, 'test', *(['--no-pub'] if args.flutter else []), '--reporter', 'expanded'],
                       cwd=harness, check=True)


if __name__ == '__main__':
    main()
