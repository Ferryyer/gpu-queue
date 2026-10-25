#!/usr/bin/env python3
"""Package the unified Apple Silicon release; no Developer ID or notarization."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def main():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('This package requires a real Apple Silicon Mac build')
    app = ROOT / 'serverbox/build/macos-qa/Build/Products/Release/GPU Queue.app'
    report = json.loads((ROOT / 'build/native-acceptance/report.json').read_text())
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    arch = platform.machine()
    # Local ad-hoc signing is required to run an Apple Silicon app. The user
    # requested direct upload, so there is no signature/launch/test gate here.
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', '--timestamp=none', str(app)], check=True)
    out = ROOT / 'build/unified-release'
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(['python3', 'scripts/package_unified_macos.py', '--app', str(app),
                    '--allow-unsigned', '--out', str(out)], cwd=ROOT, check=True)
    metadata_path = out / 'unified-release.json'
    metadata = json.loads(metadata_path.read_text())
    metadata.update(releaseTag='v2.0.2002', channel='release', sourceCommit=commit,
                    architecture=arch, minimumMacOS='13.0', signature='ad-hoc',
                    notarized=False, launchSmokePassed=False, checksSkippedByUser=True,
                    interactiveSshSftpVerified=False, installationVerified=False)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    (out / 'native-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (out / 'RELEASE-NOTES.md').write_text(f'''GPU Queue Mac 发布版，版本 2.0.2002 (2002)，仅适用 Apple Silicon（M1/M2/M3/M4 等）、macOS 13+。

源码：`{commit}`，分支 `codex/mf-12-unified-workspace`，PR #3 尚未合并。

下载 `GPU-Queue-macos-arm64-2002-unsigned.dmg`，用 SHA256SUMS 校验后挂载，拖入 Applications。请先备份现有 GPU Queue.app，优先在独立 macOS 测试用户验收；保留原有配置和钥匙串。此包只有本地 ad-hoc 签名，**没有 Apple Developer ID 签名或公证**，文件名保留 unsigned 表明它未经 Developer ID 签名或公证；本版通过 DMG 手动安装。macOS 可能阻止打开；核对来源和校验和后，在系统设置 → 隐私与安全性中选择“仍要打开”。不要全局关闭 Gatekeeper。

用户要求直接上传，本轮跳过预检、测试、签名复验和启动冒烟，仅执行生成安装包所需的编译与打包；详见 native-report.json。本版实现 MF-9 已批准的原生侧栏、紧凑任务行、按需右侧详情与日志、浅深色主题；采用 Georgia / 宋体-简展示标题、系统正文 / 苹方及 Menlo 日志。未捆绑 Anthropic 字体。本版还包含真实任务更新时间、统一 UTC 格式、缺失提示与窄列表/1.5 倍文字兼容修复。26 项相关检查与定向静态分析已通过，不重复执行。Mac 人工验收仍待执行。任务→服务器→SSH/SFTP→结果、双服务器、休眠/字体/全屏、安装覆盖与旧配置保留仍待用户本机验收。清单见仓库 docs/MAC-NATIVE-HANDOFF.md 和 MF-18。

按用户“直接完成发布版”要求，本版作为非预发布的 GitHub Latest Release 发布；发布渠道不代表已经完成 Apple 公证或 Mac 人工验收。保留旧 Widget 下载/更新入口，不向旧 Widget 自动推送统一应用，不部署服务器，不启动真实 GPU 作业。若需回退，退出此版并恢复先前备份的应用。工程错误由 GPU 任务台设计开发继续处理。
''', encoding='utf-8')
    # Every published file except the checksum manifest is covered.
    (out / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n'
        for path in sorted(out.iterdir()) if path.is_file() and path.name != 'SHA256SUMS'))
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == '__main__':
    main()
