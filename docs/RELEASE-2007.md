适用 Apple Silicon、macOS 13+。

- 左侧增加固定的“终端”入口，直接打开现有 SSH 终端页面。总览仍是默认首页；继续保留上次打开页面的恢复行为。
- 已安装用户无需重设菜单，升级后即可看到终端。收起侧栏时仍可通过终端图标进入；“更多工具”保留文件、分屏工作区等功能。
- 沿用已有终端会话、连接配置和任务库；切换页面不创建第二套终端。安装更新需要重启客户端，本地连接会断开，远端任务继续运行。

本版仍为 **ad-hoc 签名，未完成 Apple 公证**。截至发布准备时，尚未开通 Apple Developer Program，且没有 Developer ID Application 证书。公证不能仅靠代码或构建工具完成，详见 APPLE-NOTARIZATION.md。

内嵌 AI 的凭据初始化在上一版实机出现 Keychain 错误，尚未验证修复；终端与队列功能不依赖此功能。Windows 暂不提供安装包。

自动检查与原生构建证据见 native-report.json、installer-report.json；实机验收另附。验收不申请 GPU、不重跑计算任务。
