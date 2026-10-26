#!/usr/bin/env python3
"""Package the unified Apple Silicon release; no Developer ID or notarization."""
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def main():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('This package requires a real Apple Silicon Mac build')
    app = ROOT / 'serverbox/build/macos-qa/Build/Products/Release/GPU Queue.app'
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
            'success', 'checksum_mismatch', 'wrong_bundle', 'quit_timeout', 'rollback', 'cancelled'}:
        raise RuntimeError('Release requires all real macOS installer scenarios to pass')
    helpers = app / 'Contents/Helpers'
    helpers.mkdir(parents=True, exist_ok=True)
    helper = helpers / 'GPUQueueUpdater'
    subprocess.run(['swiftc', '-swift-version', '5', str(ROOT/'serverbox/macos/Updater/main.swift'),
                    '-o', str(helper)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(helper)], check=True)
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', '--timestamp=none', str(app)], check=True)
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
    (out / 'RELEASE-NOTES.md').write_text(f'''GPU Queue Mac 发布版，版本 {version} ({build})，适用 Apple Silicon、macOS 13+。

源码：`{commit}`，分支 `codex/mf-40-updater-fix`。基于 2.0.2004 应用内更新版。

更新：修复 Dart 界面版本停留在 2001、将已安装版本重复当成新版下载，最后报 invalid_update 的问题。Dart 与原生版本统一从 pubspec 生成并在构建、打包时检查；下载前读取实际已安装版本，无需更新时直接提示。安装器仍独立验证版本、大小、SHA-256、应用标识、架构和代码签名，错误提示更清楚。安装准备好后退出旧应用，保留同目录旧版备份，替换并重启；新版启动未确认时自动恢复上一版。SSH 配置、钥匙串和用户数据不参与替换。远端任务继续运行，本地终端连接会随应用重启断开。

已安装 2.0.2004：重新检查更新，选择 2005 后下载并安装即可；2004 安装器允许升级到更高版本。首次安装或从 2.0.2003 及更早版本升级：下载 `GPU-Queue-macos-arm64-{build}-unsigned.dmg`，核对 SHA256SUMS 后挂载，退出旧应用并拖入 Applications 覆盖一次。旧版没有安装器，无法自行安装本次升级；安装本版后，后续版本可在应用内完成。应用须位于可写目录，如 `~/Applications`；安装器不请求管理员权限。此包使用 ad-hoc 签名，未做 Apple Developer ID 签名或公证；如系统阻止打开，核对来源后在系统设置的隐私与安全性中选择“仍要打开”。

发布前执行 CPU/JavaScript 回归、Dart 元数据校验、Mac 原生环境检查、PTY/Swift/Flutter 测试及完整 Xcode 构建，并验证 ad-hoc 签名。真实 macOS 临时应用覆盖测试包含安装重启、摘要错误、包标识错误、退出超时、启动失败回滚和取消六种场景，结果见 installer-report.json。完整应用的人工作业验收仍见 docs/MAC-NATIVE-HANDOFF.md。保留旧 Widget 更新入口。
''', encoding='utf-8')
    # Every published file except the checksum manifest is covered.
    (out / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n'
        for path in sorted(out.iterdir()) if path.is_file() and path.name != 'SHA256SUMS'))
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == '__main__':
    main()
