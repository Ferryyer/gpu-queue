GPU Queue 更名为 **Inspire Queue**，版本 2.0.2008（build 2008）。适用 Apple Silicon、macOS 13+。

- 统一应用窗口、侧栏、菜单栏、托盘、关于页、通知、多语言提示、网页标题与当前接入文档的名称。
- 新下载使用 `Inspire-Queue-macos-arm64-2008-unsigned.dmg`，拖入的应用名为 `Inspire Queue.app`。
- 保留总览首页和左侧终端入口，继续使用原有连接配置、任务库和个人服务。
- 为旧客户端保留同内容的 `GPU-Queue-...` 安装包地址与兼容载荷。旧版升级器可能继续将应用保存在 `GPU Queue.app` 路径；显示名称已更改，需要改文件名时请退出应用后在 Finder 中改为 `Inspire Queue.app`。

`gpuqueue` Python 模块、`gpuq` 服务、GitHub 仓库地址、bundle ID、钥匙串标识、数据目录与旧小组件更新协议保留兼容。ServerBox 上游的许可证、来源和其独立 Monitor 服务名称保留。

当前仍是 **ad-hoc 未公证内部版**，尚未开通 Apple Developer Program，没有 Developer ID 签名身份。Apple 公证要求见 APPLE-NOTARIZATION.md。可选内嵌 AI 的凭据初始化此前有 Keychain 错误，本版未宣称修复。

验收不申请 GPU、不启动或重跑计算任务。构建与升级测试见 native-report.json、installer-report.json；本机验收另附。
