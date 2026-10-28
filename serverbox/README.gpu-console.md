# GPU 控制台的 ServerBox 客户端

这是定制 ServerBox 的源码快照，适合放在 GPU 控制台项目的 `serverbox/` 目录内继续开发。

包含：

- GPU 负载、显存、温度的采集与原生卡片适配。
- GPU 控制台资源注册表对接，申请新实例后更新数据来源，确认销毁后停止显示旧数据。
- 独立的“账号线程占用”卡片，显示当前账号的线程总数与程序分组。
- Mac 休眠、唤醒和网络恢复后的专用 SSH 隧道检查与重连。
- GPU 查询恢复状态显示；队列端自动重试需要配套的控制台服务代码。

## 源码与依赖

上游为 [lollipopkit/flutter_server_box](https://github.com/lollipopkit/flutter_server_box)。
版本、来源和依赖提交见 [SOURCE.json](SOURCE.json)。保留上游 [LICENSE](LICENSE)
与各依赖许可证，ServerBox 使用 AGPL-3.0。

九个已初始化的 Dart 依赖以源码形式随包提供，包含本地修改过的 `fl_lib`。
因此不会依赖仅存在于原 Mac 上的 Git 提交。`UPSTREAM.gitmodules` 记录原依赖配置；
本目录是普通源码目录，不需要作为 Git 子模块导入 GPU 控制台。

完整原生构建还需要两个上游依赖。从本目录执行：

```sh
git clone --no-checkout https://github.com/lollipopkit/IronRDP.git third_party/ironrdp
git -C third_party/ironrdp checkout --detach debc16c0039936bef2fb0ded046b171ecced3885
git -C third_party/ironrdp submodule update --init --recursive

# 仅 iOS Linux 引擎需要 ShellBox。
git clone --no-checkout https://github.com/lollipopkit/ShellBox third_party/ish-arm64
git -C third_party/ish-arm64 checkout --detach 5dfc962fe5e03fe5bc6b869b8744312ebe6af627
git -C third_party/ish-arm64 submodule update --init --recursive
```

## Inspire Queue 融合

个人任务台代码位于仓库根目录，`serverbox/` 保留原生 SSH、SFTP、进程查看、账号线程卡片、GPU 桥接和 Mac 隧道重连。
MF-12 将 Inspire Queue 任务页原生接入应用：总览、任务、服务器、设置，任务详情可进入已明确关联服务器的 SSH 终端与 SFTP 工作目录。用户仅维护服务器列表中的 SSH 配置，应用通过现有会话访问远端私有任务 socket，不再要求单独建立 8790 网页转发。

首次使用在任务页选择任务服务所在服务器并点击连接。GPU 实例与实际服务器需要显式关联；没有可靠关联时按钮禁用。任务服务故障、SSH 故障和采样过期分别显示。完整流程、安装更新命令与尚未完成的 Mac 验收见 [统一工作台说明](../docs/UNIFIED-WORKSPACE.md)。

原生界面采用暖纸色、陶土色按钮和衬线大标题，深色模式使用暖灰色。
可用 `--dart-define=GPU_QUEUE_STYLE=false` 恢复上游主题行为。旧 `GPU_QUEUE_URL` 地址解析工具仅为兼容保留，原生任务入口不再通过其启动外部浏览器。

关于页移除了捐赠按钮和其他产品推广，保留原作者、贡献者、数据来源与许可证。
源码依赖和功能入口检查未发现内购 SDK、订阅校验或高级功能锁，因而没有伪造购买状态；
已保留的 SSH、SFTP、主题、线程监控和重连均直接使用源码功能。
可选 AI 接入仍需要使用者自己的模型服务，服务商费用不由本项目承担。

## 构建

已安装的本地客户端使用 Flutter 3.47.5、ServerBox 1.0.1816。
完整 macOS 构建需要 Xcode、Rust 以及上游要求的原生构建环境。
准备依赖后，从仓库根目录执行：

```sh
# 从仓库根目录执行，沿用既有数据和凭据兼容配置。
python3 scripts/native_acceptance.py --stage build
```

构建脚本沿用既有的应用数据和登录钥匙串兼容配置；如需与原客户端并存，还应在自己的
macOS 构建配置中设置独立的 bundle identifier。发布签名按自己的开发者账号配置。
这些源码没有附带原 Mac 的签名身份、私钥、客户端数据库或连接配置。

现有 Mac 安装采用匹配版本的官方原生运行时加定制 Dart AOT 界面；该方式的说明和
SDK 驱动模板见 [线程卡片说明](scripts/thread-monitor/README.md)。完整原生构建未在
本次源码整理中执行，改变 FFI 或原生插件 API 后不能复用旧运行时。

## 服务器接入

先配置自己的 SSH 主机、密钥路径和已验证的主机指纹，再接入采集端：

1. [GPU 采集和控制台注册表](scripts/gpu-task-monitor/README.md)：读取
   `~/.local/state/serverbox-gpu/registry.json`，只输出新鲜数据；过期与不可用不显示为零。
2. [线程采集和独立卡片](scripts/thread-monitor/README.md)：当前账号的只读 `/proc` 统计。
3. [Mac 隧道恢复](scripts/macos-reconnect/README.md)：安装器针对现有个人隧道配置，
   使用前检查 SSH 别名与 LaunchAgent 名称。它不会自动创建服务器或重启模型任务。

服务器地址、实例 ID 和登录密钥由使用者本地配置，不写入本项目。
GPU 查询自动重试的队列端变更在上次部署时被共享文件系统阻塞，尚未确认启用；
上传本源码不代表服务器端已经恢复。部署时应对照控制台最新代码合并相应变更。

## 验证

```sh
python3 -m unittest discover -s scripts/gpu-task-monitor -v
python3 -m unittest discover -s scripts/thread-monitor -v
python3 -m unittest discover -s scripts/macos-reconnect -v
flutter test --timeout 30s test/widget/account_threads_card_test.dart test/unit/server/readout_test.dart
```

本次导出后重新通过 GPU 桥接 14 项、线程采集 6 项、Mac 重连 6 项测试。独立线程卡片的
4 项界面测试及 6 项既有读数测试在原源码目录已通过。不要运行代码格式化工具。

上游构建入口见 [原始 README](README.md) 和 [CLAUDE.md](CLAUDE.md)。上游说明中的
`git submodule update` 适用于原仓库；本快照使用上面的依赖准备方式。
本目录内的 `.github/` 保留上游配置，嵌入其他仓库后不会作为根工作流自动运行。
