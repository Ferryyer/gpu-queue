#!/usr/bin/env python3
"""Record native prerequisites; on a prepared Mac run tests and an unsigned QA build.

Does not install tools, modify SSH/keychain settings, sign, publish, or launch GPU
jobs. Interactive SSH/SFTP and installation acceptance remain human checks.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import time
from sync_app_version import sync

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'serverbox'
IRONRDP = 'debc16c0039936bef2fb0ded046b171ecced3885'
FLUTTER = '3.47.8'
FLUTTER_REVISION = '737ba8f885dc774b53b442759999a312c9461e4e'
RUST = '1.98.1'


def run(command, *, cwd=ROOT, log=None, timeout=60, separate_stderr=False):
    if log:
        return run_logged(command, cwd=cwd, log=log, timeout=timeout)
    stderr = ''
    try:
        result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE if separate_stderr else subprocess.STDOUT, timeout=timeout,
                                env={**os.environ, 'RUSTUP_TOOLCHAIN': RUST})
        code, output = result.returncode, result.stdout
        stderr = (result.stderr or '') if separate_stderr else ''
    except (OSError, subprocess.TimeoutExpired) as error:
        code, output = 127, str(error)
    if log:
        log.write_text(output + stderr, encoding='utf-8')
    return {'command': command, 'exitCode': code, 'output': output, 'stderr': stderr}


def run_logged(command, *, cwd, log, timeout):
    """Keep the complete log on disk and expose compiler progress during CI."""
    started = time.monotonic()
    next_heartbeat = started + 30
    with log.open('w', encoding='utf-8') as destination:
        try:
            child = subprocess.Popen(command, cwd=cwd, text=True, stdout=destination,
                                     stderr=subprocess.STDOUT,
                                     env={**os.environ, 'RUSTUP_TOOLCHAIN': RUST})
        except OSError as error:
            destination.write(str(error))
            return {'command': command, 'exitCode': 127, 'output': str(error), 'stderr': ''}
        with log.open(encoding='utf-8', errors='replace') as reader:
            try:
                while True:
                    try:
                        code = child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        code = None
                    chunk = reader.read()
                    if chunk:
                        print(chunk, end='', flush=True)
                    now = time.monotonic()
                    if code is not None:
                        break
                    if now >= next_heartbeat:
                        print(f'[build] {command[0]} still running; {int(now - started)}s elapsed', flush=True)
                        next_heartbeat = now + 30
                    if now - started >= timeout:
                        child.kill()
                        child.wait()
                        destination.write(f'\nCommand timed out after {timeout}s\n')
                        code = 124
                        break
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
    print(f'[build] {command[0]} exited {code}; {int(time.monotonic() - started)}s elapsed', flush=True)
    return {'command': command, 'exitCode': code, 'output': log.read_text(errors='replace'), 'stderr': ''}


def flutter_version(output):
    # A newly cloned SDK may print bootstrap notices before its machine JSON.
    # Require both version fields; never infer a version from human log text.
    decoder = json.JSONDecoder()
    for index, char in enumerate(output):
        if char != '{':
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except ValueError:
            continue
        if isinstance(value, dict) and 'frameworkRevision' in value and 'frameworkVersion' in value:
            return value
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['preflight', 'tests', 'build'], default='preflight')
    parser.add_argument('--flutter', default='flutter')
    parser.add_argument('--package-only', action='store_true',
                        help='User-requested direct preview: skip prerequisite checks and tests; compile the app only')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/native-acceptance')
    args = parser.parse_args()
    # Check even package-only builds: UI and CFBundleVersion must agree.
    sync(APP, check=True)
    args.out.mkdir(parents=True, exist_ok=True)
    report = {'recordedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'platform': platform.system(), 'architecture': platform.machine(),
              'stage': args.stage, 'checks': {}, 'commands': [],
              'interactiveSshSftpVerified': False, 'installationVerified': False,
              'macBuildVerified': False}
    checks = report['checks']
    report['sourceCommit'] = run(['git', 'rev-parse', 'HEAD'])['output'].strip()
    report['sourceDirty'] = bool(run(['git', 'status', '--porcelain'])['output'].strip())
    if args.package_only:
        if args.stage != 'build' or platform.system() != 'Darwin':
            parser.error('--package-only requires --stage build on macOS')
        report['checksSkippedByUser'] = True
        report['testsSkippedByUser'] = True
    else:
        preflight(args, report)
    report['ready'] = not args.package_only and all(checks.values())
    report['missing'] = [name for name, passed in checks.items() if not passed]

    def save():
        (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    save()
    if args.stage == 'preflight' or (not args.package_only and not report['ready']):
        print(json.dumps({'ready': report['ready'], 'missing': report['missing'],
                          'report': str(args.out / 'report.json')}, ensure_ascii=False))
        return 0 if report['ready'] else 2

    # Flutter build hooks retain PATH but filter custom environment variables.
    rustup = shutil.which('rustup')
    launchers = args.out.resolve() / 'toolchain-bin'
    launchers.mkdir(exist_ok=True)
    wrapper = launchers / 'rustup'
    values = {'RUSTUP_TOOLCHAIN': RUST}
    for key in ['RUSTUP_HOME', 'CARGO_HOME']:
        if key in os.environ:
            values[key] = os.environ[key]
    wrapper.write_text('#!/bin/sh\n' + ''.join(
        'export ' + key + '=' + shlex.quote(value) + '\n' for key, value in values.items()
    ) + 'exec ' + shlex.quote(rustup) + ' "$@"\n', encoding='utf-8')
    wrapper.chmod(0o700)
    os.environ['PATH'] = str(launchers) + os.pathsep + os.environ.get('PATH', '')
    commands = [([args.flutter, 'pub', 'get', '--enforce-lockfile'], APP)]
    if not args.package_only:
        commands += test_commands(args)
    if args.stage == 'build':
        commands += [
            ([args.flutter, 'build', 'macos', '--config-only', '--release',
              '--dart-define=SERVERBOX_DATA_NAME=ServerBoxH100',
              '--dart-define=FL_LIB_MACOS_DATA_PROTECTION_KEYCHAIN=false',
              '--dart-define=FL_LIB_MACOS_SECURE_ACCOUNT=local.ferry.serverbox.h100'], APP),
            (['xcodebuild', '-workspace', 'macos/Runner.xcworkspace', '-scheme', 'Runner',
              '-configuration', 'Release', '-derivedDataPath', 'build/macos-qa',
              'ARCHS=' + platform.machine(), 'ONLY_ACTIVE_ARCH=YES',
              'CODE_SIGNING_ALLOWED=NO', 'CODE_SIGNING_REQUIRED=NO',
              'CODE_SIGN_IDENTITY=', 'DEVELOPMENT_TEAM=', 'build'], APP),
        ]
    for index, (command, cwd) in enumerate(commands, 1):
        log = args.out / f'{index:02d}.log'
        print(f'Running {index}/{len(commands)}: {command[0]} {command[1]}', flush=True)
        result = run(command, cwd=cwd, log=log, timeout=3600)
        report['commands'].append({'command': command, 'exitCode': result['exitCode'], 'log': log.name})
        save()
        if result['exitCode']:
            print(f'Failed; see {log}', file=sys.stderr)
            print(result['output'][-12000:], file=sys.stderr)
            return 1
    if args.stage == 'build':
        app = APP / 'build/macos-qa/Build/Products/Release/Inspire Queue.app'
        report['macBuildProduced'] = app.is_dir()
        report['macBuildVerified'] = not args.package_only and app.is_dir()
        report['qaApp'] = str(app)
        report['signedForDistribution'] = False
        save()
        if not report['macBuildProduced']:
            return 1
    print('Package generation completed. Human acceptance remains unverified.')
    return 0


def preflight(args, report):
    checks = report['checks']
    checks['macOS'] = platform.system() == 'Darwin'
    flutter = run([args.flutter, '--version', '--machine'], timeout=300, separate_stderr=True)
    version = flutter_version(flutter['output'])
    report['flutterProbe'] = flutter
    report['flutterVersion'] = version.get('frameworkVersion')
    report['flutterRevision'] = version.get('frameworkRevision')
    checks['flutterPinned'] = (flutter['exitCode'] == 0 and report['flutterVersion'] == FLUTTER
                               and report['flutterRevision'] == FLUTTER_REVISION)
    for label, command in {
        'xcode': ['xcodebuild', '-version'],
        'macSdk': ['xcrun', '--sdk', 'macosx', '--show-sdk-path'],
        'clang': ['clang', '--version'],
        'swift': ['swift', '--version'],
        'rust': ['rustup', 'run', RUST, 'rustc', '--version'],
        'cargo': ['rustup', 'run', RUST, 'cargo', '--version'],
    }.items():
        result = run(command)
        report[label] = result
        checks[label] = result['exitCode'] == 0
    target = 'aarch64-apple-darwin' if platform.machine() == 'arm64' else 'x86_64-apple-darwin'
    targets = run(['rustup', 'target', 'list', '--installed', '--toolchain', RUST])
    checks['rustMacTarget'] = targets['exitCode'] == 0 and target in targets['output'].splitlines()
    dependency = APP / 'third_party/ironrdp'
    revision = run(['git', '-C', str(dependency), 'rev-parse', 'HEAD'])
    report['ironRdpCommit'] = revision['output'].strip() if revision['exitCode'] == 0 else None
    checks['ironRdpPinned'] = report['ironRdpCommit'] == IRONRDP
    submodules = run(['git', '-C', str(dependency), 'submodule', 'status', '--recursive'])
    checks['ironRdpSubmodules'] = submodules['exitCode'] == 0 and all(
        not line.startswith(('-', '+', 'U')) for line in submodules['output'].splitlines())


def test_commands(args):
    return [
        ([args.flutter, 'analyze', '--no-pub', '--no-fatal-infos', '--no-fatal-warnings',
          'lib/core/update', 'lib/main.dart', 'packages/fl_lib/lib/src/core/update.dart',
          'lib/core/gpu_queue', 'lib/view/page/gpu_queue', 'lib/view/page/feishu',
          'lib/core/calendar', 'lib/view/page/overview', 'lib/view/page/home_tab.dart',
          'lib/view/page/home.dart', 'lib/data/model/app/tab.dart',
          'test/unit/app/mac_update_release_test.dart', 'test/unit/app/mac_update_bridge_test.dart',
          'lib/core/ssh_bundle', 'lib/view/widget/client_bundle_setup.dart',
          'lib/app.dart', 'lib/intro.dart', 'lib/view/page/setting/entry.dart',
          'lib/view/page/setting/entries/ssh.dart', 'lib/view/page/setting/entries/app.dart',
          'lib/core/service/diagnostics_upload.dart', 'lib/data/model/app/diagnostics_level.dart',
          'lib/view/widget/crash_report_dialog.dart', 'lib/main.dart'], APP),
        ([sys.executable, 'scripts/test_pty_native.py', '--flutter', args.flutter], ROOT),
        (['swiftc', '-swift-version', '5', 'scripts/macos-reconnect/TunnelRecovery.swift',
          '-o', str(args.out.resolve() / 'TunnelRecovery')], APP),
        ([sys.executable, '-m', 'unittest', 'discover', '-s', 'scripts/macos-reconnect', '-v'], APP),
        ([args.flutter, 'test', '--no-pub', 'test/unit/app/queue_protocol_test.dart',
          'test/unit/app/queue_session_test.dart', 'test/unit/app/queue_presentation_test.dart',
          'test/unit/app/queue_resource_widget_test.dart', 'test/unit/app/mac_update_release_test.dart',
          'test/unit/app/queue_workspace_widget_test.dart', 'test/unit/app/feishu_task_widget_test.dart',
          'test/unit/app/local_calendar_test.dart', 'test/unit/app/overview_layout_test.dart',
          'test/unit/app/mac_update_bridge_test.dart',
          'test/widget/terminal_reconnect_test.dart',
          'test/unit/app/app_tab_test.dart',
          'test/unit/ssh/client_bundle_test.dart', 'test/unit/app/virt_intro_test.dart',
          'test/unit/app/diagnostics_sync_test.dart', 'test/unit/app/diagnostics_level_test.dart',
          'test/unit/app/diagnostics_retire_full_test.dart', 'test/widget/crash_report_dialog_test.dart'], APP),
    ]


if __name__ == '__main__':
    raise SystemExit(main())
