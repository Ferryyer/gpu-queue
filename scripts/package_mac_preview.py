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
                    interactiveSshSftpVerified=False, installationVerified=False)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    (out / 'native-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (out / 'RELEASE-NOTES.md').write_text(f'''GPU Queue Mac 发布版，版本 {version} ({build})，适用 Apple Silicon、macOS 13+。

源码：`{commit}`，分支 `codex/mf-33-release`。基于 2.0.2002 统一桌面应用，合入已合并的 PR #6。

更新：旧 GPU 只读查询超时后，按个人偏好为已启动但未投放的任务补申请一次；重启不重复申请。修复 GPU 内部查询超时识别、旧通知重复触发探测和旧卡通知错误阻塞补申请。申请提交回执不明时仍保留原 UUID 核查；网页和原生任务详情显示真实阶段与申请编号。服务器适配器已在个人服务更新，安装客户端不会替换服务器代码。

下载 `GPU-Queue-macos-arm64-{build}-unsigned.dmg`，核对 SHA256SUMS 后挂载，退出旧应用并拖入 Applications。保留 SSH 配置和钥匙串。此包使用 ad-hoc 签名，未做 Apple Developer ID 签名或公证；如系统阻止打开，核对来源后在系统设置的隐私与安全性中选择“仍要打开”。

发布前执行 CPU 调度回归、JavaScript 更新兼容测试、Mac 原生环境检查、PTY/Swift/Flutter 测试及完整 Xcode 构建，并验证 ad-hoc 签名，原生结果见 native-report.json。真实服务器 SSH/SFTP、安装覆盖、休眠、字体和全屏的人工作业验收尚未在本轮完成；详见 docs/MAC-NATIVE-HANDOFF.md。保留旧 Widget 更新入口。若需回退，退出新版并恢复此前备份的应用。
''', encoding='utf-8')
    # Every published file except the checksum manifest is covered.
    (out / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n'
        for path in sorted(out.iterdir()) if path.is_file() and path.name != 'SHA256SUMS'))
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == '__main__':
    main()
