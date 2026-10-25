## GPU Queue 与 ServerBox 融合

基线为 GPU Queue `main` 的 `77255d9`；导入 `codex/serverbox-h100` 的 `05c7015e29a58e3046be72871afadee12701fcda` 中完整 `serverbox/`，保留其源码、依赖、来源清单和 AGPL-3.0 许可证。

网页沿用暖纸色、衬线标题和陶土色按钮，实现逐实例生命周期与逐卡利用率/显存/温度、90 秒过期判断、当前页面最近 30 分钟趋势、JSON 导出。GiB 由 MiB / 1024 换算。趋势按实际采样时间去重，不把网页轮询当新采样。关闭、未知、过期或明显未来时间的实时指标均隐藏。

`GET /api/host` 直接复用 `serverbox/scripts/thread-monitor/status.py` 的 UID 限定只读采样，缓存 5 秒，不读取命令行或凭据。网页展开“账号线程占用”查看分组与继承限制；失败时标记不可用，并将上次成功结果明确分开。接口使用现有私有 SSH 网页入口和 Host 校验。

原生客户端的服务器详情工具栏和“关于”页提供 GPU Queue 入口，使用已有 HTTP 回环转发。原生界面同步暖纸色与陶土色，支持暖灰深色模式。构建选项见 `serverbox/README.gpu-console.md`。此融合保留原生 SSH/SFTP、进程查看、账号线程卡片、GPU XML 桥接和 Mac 唤醒/网络恢复重连；不会安装或启动这些个人服务。

## 付费内容核对

检查范围：原生应用 `lib/`、`pubspec.yaml`、`pubspec.lock` 以及随包共享库的功能入口。未发现内购 SDK、订阅/购买校验或付费功能开关。关于页捐赠按钮和其他产品推广已移除；上游作者、贡献者、数据来源和许可证保留。没有购买状态模拟，也没有解锁调用。

本地监控、趋势、导出、线程统计、SSH/SFTP 和重连不依赖订阅。可选 AI 模型服务、iCloud/WebDAV 等第三方服务仍由用户自行配置，其外部费用不会因源码构建消失。本改动未实现免费的远程模型服务。

## 验证

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/*.cjs tests/*.test.js
node scripts/build.mjs
node --check web/app.js
python3 -m unittest discover -s serverbox/scripts/gpu-task-monitor -v
python3 -m unittest discover -s serverbox/scripts/thread-monitor -v
python3 tests/browser_monitor_check.py
python3 tests/browser_typography_check.py
```

通过 60 项 Python、32 项 Node、14 项 GPU 桥接、6 项线程采样测试。
Chromium 验证了线程展开、GPU 指标、真实采样去重后的趋势、JSON 下载、过期隐藏和 320–1440px 无横向溢出；排版检查覆盖 7 种宽度、模式切换、搜索、弹窗、深色系统偏好及减少动画。
浏览器数据为 CPU 隔离假数据，不是线上 GPU 读数。

Linux 环境没有 Flutter 和 Swift 编译器，尚未执行新原生 Dart 测试、Flutter 静态分析/macOS 完整构建或 6 项 Swift 重连测试。完整构建还需 README 中列出的 IronRDP，iOS 另需 ShellBox；这两个依赖未随快照提供。没有复用用户的旧运行时生成新安装包，也没有部署线上服务。

GPU 查询重试：导入的桥接器可以显示生产者提供的 `monitor` 恢复状态，但当前根目录生产者保留原有查询失败行为。本次未启用源码说明中提到、未包含在该分支里的诊断重试/归档变更，不宣称已解决线上查询恢复问题。
