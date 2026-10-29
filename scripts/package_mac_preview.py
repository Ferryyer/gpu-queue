#!/usr/bin/env python3
"""Package the unified Apple Silicon release; no Developer ID or notarization."""
import hashlib
import json
from pathlib import Path
import platform
import plistlib
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def main():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('This package requires a real Apple Silicon Mac build')
    app = ROOT / 'serverbox/build/macos-qa/Build/Products/Release/Inspire Queue.app'
    report = json.loads((ROOT / 'build/native-acceptance/report.json').read_text())
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    arch = platform.machine()
    version, build = re.search(r'^version: ([0-9.]+)\+([0-9]+)$',
                              (ROOT/'serverbox/pubspec.yaml').read_text(), re.M).groups()
    tag = 'v'+version
    if not report.get('macBuildVerified') or report.get('sourceCommit') != commit:
        raise RuntimeError('Release requires native tests and build evidence for this exact commit')
    installer_report = json.loads((ROOT / 'build/mac-updater-tests/report.json').read_text())
    scenarios = {item['scenario'] for item in installer_report.get('scenarios', []) if item.get('passed')}
    if not installer_report.get('native') or scenarios != {
            'success', 'legacy_payload', 'checksum_mismatch', 'wrong_bundle', 'quit_timeout', 'rollback', 'cancelled'}:
        raise RuntimeError('Release requires all real macOS installer scenarios to pass')
    helpers = app / 'Contents/Helpers'
    helpers.mkdir(parents=True, exist_ok=True)
    helper = helpers / 'GPUQueueUpdater'
    subprocess.run(['swiftc', '-swift-version', '5', str(ROOT/'serverbox/macos/Updater/main.swift'),
                    '-o', str(helper)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(helper)], check=True)
    entitlements = ROOT / 'serverbox/macos/Runner/Preview.entitlements'
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', '--timestamp=none',
                    '--entitlements', str(entitlements), str(app)], check=True)
    signed_entitlements = plistlib.loads(subprocess.check_output(
        ['codesign', '--display', '--entitlements', ':-', str(app)], stderr=subprocess.DEVNULL))
    if signed_entitlements.get('com.apple.security.files.user-selected.read-write') is not True:
        raise RuntimeError('Release must retain the native file picker entitlement')
    if signed_entitlements.get('com.apple.security.app-sandbox', False):
        raise RuntimeError('Desktop preview must preserve local terminal and SSH access')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    out = ROOT / 'build/unified-release'
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(['python3', 'scripts/package_unified_macos.py', '--app', str(app),
                    '--allow-unsigned', '--out', str(out)], cwd=ROOT, check=True)
    metadata_path = out / 'unified-release.json'
    metadata = json.loads(metadata_path.read_text())
    metadata.update(releaseTag=tag, channel='release', sourceCommit=commit,
                    architecture=arch, minimumMacOS='13.0', signature='ad-hoc',
                    notarized=False, launchSmokePassed=False, checksSkippedByUser=False,
                    interactiveSshSftpVerified=False, installationVerified=False,
                    inAppInstaller=True, installerNativeScenariosVerified=True)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    (out / 'native-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (out / 'installer-report.json').write_text(json.dumps(installer_report, ensure_ascii=False, indent=2) + '\n')
    (out / 'RELEASE-NOTES.md').write_text(
        f'Inspire Queue {version} ({build}) · Mac 员工内部版\n\n源码：`{commit}`\n\n'
        + (ROOT / f'docs/RELEASE-{build}.md').read_text(), encoding='utf-8')
    (out / 'EMPLOYEE-SETUP.md').write_text((ROOT / 'docs/EMPLOYEE-SETUP.md').read_text(), encoding='utf-8')
    (out / 'APPLE-NOTARIZATION.md').write_text((ROOT / 'docs/APPLE-NOTARIZATION.md').read_text(), encoding='utf-8')
    # Every published file except the checksum manifest is covered.
    (out / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n'
        for path in sorted(out.iterdir()) if path.is_file() and path.name != 'SHA256SUMS'))
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == '__main__':
    main()
