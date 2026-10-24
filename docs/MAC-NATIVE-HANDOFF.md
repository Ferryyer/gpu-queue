# MF-12 · Mac 原生验收接手包

维护仓库 `Ferryyer/gpu-queue`，分支 `codex/mf-12-unified-workspace`，PR #3；依赖 PR #1 的 `6a0b990`，不合并、不生产部署。UI 修正基线是 `5fc0e0afac822143f44fae0bcdd70a5a5c2acef1`。接手包的 `CHECKOUT.txt` 和任务本轮评论给出**包含本文件及 PTY 加载修正的完整提交 SHA**；在新目录检出该 SHA，不在已有安装或验收树覆盖文件。

## 已验证与责任边界

Linux 已用真实 Clang 编译 vendored PTY C 库，并运行真实生产 build hook 的本地终端测试：shell 输入/输出、环境/目录、resize、退出状态与信号。发现旧 `DynamicLibrary.open` 文件名不经过 code-asset 映射，已改用 `@Native` 精确指向 hook 输出的 `package:flutter_pty/flutter_pty`。这要求完整重建原生运行时，不能复用旧版 Mac 运行时只替换 AOT。

本地测试只证明 PTY 库，不证明 Mac 应用、SSH、SFTP、安装或更新。Mac 构建、签名工具和交互验收在 Linux 上无法代做。平台 runtime 清单目前只有 markflow CPU，没有已连接的 Mac。

工程后续负责人：GPU 任务台设计开发负责构建错误和代码修复；MF-9 的产品设计师负责独立 UI 复验；Mac 本机操作由 linlishuo 或其指定的 Mac 验收执行者接手。当前尚未确认某台 Mac 已接单，不能把交接说明写成实机已运行。

## 准备固定依赖

1. macOS **13+**，原生架构为 arm64 或 x86_64；完整 Xcode（不仅 Command Line Tools）、已接受本机 Xcode 许可，`xcodebuild -version`、`xcrun --sdk macosx --show-sdk-path`、`clang --version`、`swift --version` 均应成功。不要降低部署目标 13.0。
2. Flutter **3.47.8 / Dart 3.13.7**。将这个 SDK 的 `bin` 加入本次终端 PATH；不要升级源码 lockfile。`flutter pub get --enforce-lockfile` 必须成功。
3. rustup 与 Rust **1.98.1**、本机 Apple target。三个 Rust crate 的 `rust-toolchain.toml` 均锁此版本。已有 rustup 时，在仓库根目录执行：

```sh
rustup toolchain install 1.98.1 --profile minimal --component rustfmt --component clippy
# Apple Silicon 用这一行；Intel 改为 x86_64-apple-darwin。
rustup target add --toolchain 1.98.1 aarch64-apple-darwin
export RUSTUP_TOOLCHAIN=1.98.1
```

`RUSTUP_TOOLCHAIN` 只影响本终端。Flutter hooks 会过滤自定义环境变量，因此验收脚本会额外生成本次构建专用的 rustup launcher：固定 1.98.1 并保留已配置的 RUSTUP_HOME/CARGO_HOME，避免 rustup 另行下载所有手机/桌面 target。不要更改项目的 toolchain 文件来绕过版本。

4. IronRDP 固定源码；以下命令仅在新的检出目录执行。若目录已存在，先核对 `git rev-parse HEAD` 和工作区，保留已有修改，不使用 reset/clean：

```sh
git clone --no-checkout https://github.com/lollipopkit/IronRDP.git serverbox/third_party/ironrdp
git -C serverbox/third_party/ironrdp checkout --detach debc16c0039936bef2fb0ded046b171ecced3885
git -C serverbox/third_party/ironrdp submodule update --init --recursive
```

macOS 不需要 ShellBox（仅 iOS Linux 引擎需要）。九个 Dart 依赖已 vendored。Rust crates.io 依赖由提交内 Cargo.lock 决定。不要运行上游发布、Homebrew 同步或隧道安装脚本作为构建前置操作。

## 一次性预检、测试和 QA 构建

从仓库根目录执行（可用 `--flutter /具体SDK/bin/flutter` 指定 SDK）：

```sh
python3 scripts/native_acceptance.py --stage preflight
python3 scripts/native_acceptance.py --stage tests
python3 scripts/native_acceptance.py --stage build
```

预检缺任一项则退出 2，写 `build/native-acceptance/report.json`；tests/build 不会在缺依赖或非 Mac 时继续。每个真正执行的命令独立写日志并记录退出码，失败即停。tests 会运行实际 PTY hook 与应用原生 hooks，build 先通过测试再构建。

QA 构建先 `flutter build macos --config-only --release` 写配置，再以本机架构运行 Xcode build，命令行禁用签名（`CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY= DEVELOPMENT_TEAM=`），避免使用源码中上游开发者团队。没有修改项目团队身份或 bundle ID。候选 app 位置：

`serverbox/build/macos-qa/Build/Products/Release/GPU Queue.app`

保留源码现有的 `SERVERBOX_DATA_NAME=ServerBoxH100`、`FL_LIB_MACOS_DATA_PROTECTION_KEYCHAIN=false`、`FL_LIB_MACOS_SECURE_ACCOUNT=local.ferry.serverbox.h100`。不要改 bundle ID 或钥匙串定义后宣称旧配置保留。首次验收在专门的 macOS 测试用户执行，保留已有安装与钥匙串；完成隔离验收后再在原用户下验证兼容性。

完整脚本目前没有在 Mac 执行；成功与否以 Mac 生成的报告/日志为准。Mac 上打开 QA app 前用 `lipo -archs` 检查 `Contents/MacOS` 与框架架构，并查看 Info.plist 的 `2.0.2000 / 2000`。QA app 未签名，不能当作正式分发版本或自动更新候选。

PR 分支另带 `.github/workflows/mf12-native-qa.yml`：仅在此候选分支的相关变更上触发 macos-15 构建，固定 Flutter 提交、Rust 和 IronRDP，不使用签名密钥或部署凭据。它运行相同验收脚本，成功后用 ditto 保留 executable mode/资源并生成 QA ZIP/SHA-256；失败时也上传已有报告，保留 7 天。具体运行是否已被 GitHub 接受、是否成功以 Actions 结果为准。CI 构建也不证明交互、真实安装/更新或用户 Mac 已验收。

## 实机交互清单（每项记录结果及证据）

- 在同一窗口添加两台已有测试 SSH 服务器。使用隔离的任务库和无 GPU 的结果 fixture，不连接或启动真实 GPU 队列。
- 任务 → 显式关联实例/服务器 A → SSH 终端核对 hostname/目录 → 返回同一任务 → SFTP 工作目录 → 返回已保存结果；对 B 重复。切换后终端、文件和 GPU 必须一致。无关联时不能猜机器；编辑 SSH 目的地后原关联应失效。
- 测试 SSH 可用但任务服务失败、无权限、空任务/空实例、断线/重连。旧 GPU 指标隐藏并标非实时；服务失败不能把 SSH 显示为离线。
- 未授权任务在 Auto、切模式、刷新和重连后都不获授权；Auto/断线禁用启动。停止先取消再确认，启动 digest 失败与回执不明不得重放。此处使用隔离 CPU fixture，不以真实 GPU 作业测试。
- 启动按钮前资源需求/固定版本可读；逐 GPU 指标、缺测、过期与中文步骤状态可读。连续两轮刷新保持焦点、选择、任务/日志滚动。
- 中文字体、浅/深色、全屏、窗口缩放、菜单栏摘要与入口、休眠/唤醒和网络恢复；Safari 网页缩放/全屏与 390/640/800px 键盘闭环。Swift 恢复模块使用本机编译和实机事件验证，不运行旧安装脚本替换现有隧道。
- 只在隔离用户中做 QA DMG 挂载/覆盖测试，保存 SHA-256；再验证旧用户配置和钥匙串保留。正式签名/公证和发布渠道更新仍需拥有者开发者环境，不能用未签名包替代。

报告中的 `interactiveSshSftpVerified` 和 `installationVerified` 默认永远为 false，脚本不会因构建通过自行把人工项目标绿。验收执行者另附带时间的清单/录像/截图；脱敏后回传 report.json、失败命令对应日志、架构与版本信息。

如需生成明确标识的 QA 包（不是正式版）：

```sh
python3 scripts/package_unified_macos.py --app 'serverbox/build/macos-qa/Build/Products/Release/GPU Queue.app' --allow-unsigned
```

不运行生产发布命令；旧 Widget ZIP 不代表统一版，旧更新入口在本轮保持原状。

## Linux 继续验证 PTY 的实际配置

本任务下载 Ubuntu Clang 14 包至任务私有工具目录，复用本人既有 GCC 13 sysroot、头文件和链接器，不用 sudo、不改系统 PATH。Clang wrapper 明确传 `--sysroot`、`--gcc-toolchain` 与 `-B`。仅把任务 wrapper 目录加入当前命令 PATH，然后执行：

```sh
python3 scripts/test_pty_native.py --flutter /具体SDK/bin/flutter
```

未配置 Clang 时的旧错误为 `No compiler configured on host linux_x64`；配置后暴露并修复的错误为 `Failed to load dynamic library 'libflutter_pty.so'`。这两个问题与 SSH 登录故障、GPFS 存储故障分别处理。整应用后续 Rust/native 依赖错误及退出码见本轮交付的原生验证报告，不把独立 PTY 通过称为整应用通过。
