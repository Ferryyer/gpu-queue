#!/usr/bin/env python3
"""Package a real Apple Silicon acceptance build; no Developer ID or notarization."""
import hashlib
import json
from pathlib import Path
import platform
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def main():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('This preview requires a real Apple Silicon Mac build')
    app = ROOT / 'serverbox/build/macos-qa/Build/Products/Release/GPU Queue.app'
    report = json.loads((ROOT / 'build/native-acceptance/report.json').read_text())
    if not report['macBuildVerified'] or not report['commands'] or any(
            item['exitCode'] for item in report['commands']):
        raise RuntimeError('Native acceptance build has not passed')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if report['sourceCommit'] != commit:
        raise RuntimeError('Build evidence does not match this source commit')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    binary = app / 'Contents/MacOS' / info['CFBundleExecutable']
    arch = subprocess.check_output(['lipo', '-archs', str(binary)], text=True).strip()
    if arch != 'arm64':
        raise RuntimeError(f'Expected arm64 app, got {arch}')
    # Apple Silicon requires a code signature. Local ad-hoc signing supplies
    # integrity only, without claiming the upstream team's iCloud entitlements.
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', '--timestamp=none', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    out = ROOT / 'build/unified-release'
    out.mkdir(parents=True, exist_ok=True)
    log = out / 'launch-smoke.log'
    with log.open('w') as output:
        process = subprocess.Popen([str(binary)], stdout=output, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=10)
            raise RuntimeError(f'App exited during startup (exit {code}); see {log}')
        except subprocess.TimeoutExpired:
            pass
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    subprocess.run(['python3', 'scripts/package_unified_macos.py', '--app', str(app),
                    '--allow-unsigned', '--out', str(out)], cwd=ROOT, check=True)
    metadata_path = out / 'unified-release.json'
    metadata = json.loads(metadata_path.read_text())
    metadata.update(releaseTag='v2.0.2000-preview.1', sourceCommit=commit,
                    architecture=arch, minimumMacOS='13.0', signature='ad-hoc',
                    notarized=False, launchSmokePassed=True,
                    interactiveSshSftpVerified=False, installationVerified=False)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    (out / 'native-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (out / 'RELEASE-NOTES.md').write_text(f'''Mac 验收预览版，版本 2.0.2000 (2000)，仅适用 Apple Silicon（M1/M2/M3/M4 等）、macOS 13+。

源码：`{commit}`，分支 `codex/mf-12-unified-workspace`，PR #3 尚未合并。

下载 `GPU-Queue-macos-arm64-2000-unsigned.dmg`，用 SHA256SUMS 校验后挂载，拖入 Applications。请先备份现有 GPU Queue.app，优先在独立 macOS 测试用户验收；保留原有配置和钥匙串。此包只有本地 ad-hoc 签名，**没有 Apple Developer ID 签名或公证**，文件名保留 unsigned 表明不能用于正式自动更新。macOS 可能阻止打开；核对来源和校验和后，在系统设置 → 隐私与安全性中选择“仍要打开”。不要全局关闭 Gatekeeper。

真实 macOS 构建前执行原生 PTY、Swift 重连及应用定向测试，构建后验证 arm64、签名完整性并进行 10 秒启动冒烟检查；详见 native-report.json。启动冒烟不代表交互验收。任务→服务器→SSH/SFTP→结果、双服务器、休眠/字体/全屏、安装覆盖与旧配置保留仍待用户本机验收。清单见仓库 docs/MAC-NATIVE-HANDOFF.md 和 MF-18。

这是供用户先安装再验收的预览发布。保留旧 Widget 下载/更新入口；不将本包推入稳定自动更新，不部署服务器，不启动真实 GPU 作业。若需回退，退出此版并恢复先前备份的应用。工程错误由 GPU 任务台设计开发继续处理。
''', encoding='utf-8')
    # Every published file except the checksum manifest is covered.
    (out / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n'
        for path in sorted(out.iterdir()) if path.is_file() and path.name != 'SHA256SUMS'))
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == '__main__':
    main()
