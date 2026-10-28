#!/usr/bin/env python3
"""Run production queue tests without unrelated app native build hooks."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--flutter', default='flutter')
    parser.add_argument('--widgets', action='store_true', help='Also render production GPU monitor widgets on the CPU Flutter test engine')
    parser.add_argument('--offline', action='store_true', help='Use already cached pub dependencies')
    args = parser.parse_args()
    build = ROOT/'build'
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='queue-dart-', dir=build) as folder:
        harness = Path(folder)
        (harness/'test').mkdir()
        ui = '  material_ui: 1.5.0\n  cupertino_ui: 1.1.1\n  url_launcher: 6.3.2\n' if args.widgets else ''
        (harness/'pubspec.yaml').write_text("name: queue_protocol_checks\nenvironment:\n  sdk: '>=3.11.0 <4.0.0'\ndependencies:\n  flutter:\n    sdk: flutter\n"+ui+"dev_dependencies:\n  flutter_test:\n    sdk: flutter\nflutter:\n  uses-material-design: true\n")
        names = ['queue_protocol_test.dart', 'queue_session_test.dart', 'queue_presentation_test.dart', 'mac_update_release_test.dart', 'mac_update_bridge_test.dart', 'local_calendar_test.dart']
        if args.widgets:
            names += ['queue_resource_widget_test.dart', 'queue_workspace_widget_test.dart', 'feishu_task_widget_test.dart', 'overview_layout_test.dart']
        for name in names:
            source = (ROOT/'serverbox/test/unit/app'/name).read_text()
            (harness/'test'/name).write_text(source)
        subprocess.run([args.flutter, 'pub', 'get', *(['--offline'] if args.offline else [])], cwd=harness, check=True)
        # Resolve the real production library; no copies, mocks, or native app
        # hooks. Only the small declared dependency graph is built by this harness.
        config = harness/'.dart_tool/package_config.json'
        packages = json.loads(config.read_text())
        packages['packages'].append({'name': 'server_box', 'rootUri': (ROOT/'serverbox').as_uri(), 'packageUri': 'lib/', 'languageVersion': '3.11'})
        config.write_text(json.dumps(packages))
        subprocess.run([args.flutter, 'test', '--no-pub'], cwd=harness, check=True)

if __name__ == '__main__':
    main()
