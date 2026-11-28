#!/usr/bin/env python3
"""Run production queue and file search tests without app native build hooks."""
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
    parser.add_argument('--ssh-bundle', action='store_true', help='Verify ZIP parsing, private key matching and protected SSH configuration')
    parser.add_argument('--offline', action='store_true', help='Use already cached pub dependencies')
    args = parser.parse_args()
    build = ROOT/'build'
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='queue-dart-', dir=build) as folder:
        harness = Path(folder)
        (harness/'test').mkdir()
        ui = '  material_ui: 1.5.0\n  cupertino_ui: 1.1.1\n  url_launcher: 6.3.2\n  clock: ^1.1.3\n' if args.widgets else ''
        if args.ssh_bundle:
            ui += f'  archive: ^4.3.0\n  crypto: ^3.0.0\n  pointycastle: ^4.0.0\n  pinenacl: ^0.6.0\n  dartssh2:\n    path: "{ROOT / "serverbox/packages/dartssh2"}"\n'
        (harness/'pubspec.yaml').write_text("name: queue_protocol_checks\nenvironment:\n  sdk: '>=3.11.0 <4.0.0'\ndependencies:\n  flutter:\n    sdk: flutter\n  logging: ^1.3.0\n"+ui+"dev_dependencies:\n  flutter_test:\n    sdk: flutter\nflutter:\n  uses-material-design: true\n")
        names = ['queue_protocol_test.dart', 'queue_session_test.dart', 'queue_presentation_test.dart', 'mac_update_release_test.dart', 'mac_update_bridge_test.dart', 'local_calendar_test.dart', 'result_preview_test.dart']
        if args.widgets:
            names += ['queue_resource_widget_test.dart', 'queue_workspace_widget_test.dart', 'feishu_task_widget_test.dart', 'overview_layout_test.dart']
        for name in names:
            source = (ROOT/'serverbox/test/unit/app'/name).read_text()
            (harness/'test'/name).write_text(source)
        name = 'path_resolver_test.dart'
        (harness/'test'/name).write_text((ROOT/'serverbox/test/unit/file'/name).read_text())
        if args.ssh_bundle:
            (harness/'test/client_bundle_test.dart').write_text((ROOT/'serverbox/test/unit/ssh/client_bundle_test.dart').read_text())
            (harness/'test/device_login_test.dart').write_text((ROOT/'serverbox/test/unit/ssh/device_login_test.dart').read_text())
        subprocess.run([args.flutter, 'pub', 'get', *(['--offline'] if args.offline else [])], cwd=harness, check=True)
        # The real FileBackend imports fl_lib for its logger. Its full package
        # builds a Rust theme store, so expose only the logger used here.
        logger_lib = harness/'test_support/lib'
        logger_lib.mkdir(parents=True)
        (logger_lib/'fl_lib.dart').write_text(
            "import 'package:logging/logging.dart';\n\n"
            "abstract final class Loggers {\n"
            "  static final app = Logger('App');\n"
            "}\n"
        )
        # Exercise the real server_box sources through the minimal package graph.
        config = harness/'.dart_tool/package_config.json'
        packages = json.loads(config.read_text())
        packages['packages'].append({'name': 'server_box', 'rootUri': (ROOT/'serverbox').as_uri(), 'packageUri': 'lib/', 'languageVersion': '3.11'})
        packages['packages'].append({'name': 'fl_lib', 'rootUri': logger_lib.parent.as_uri(), 'packageUri': 'lib/', 'languageVersion': '3.11'})
        config.write_text(json.dumps(packages))
        subprocess.run([args.flutter, 'test', '--no-pub'], cwd=harness, check=True)

if __name__ == '__main__':
    main()
