# gpu-queue

GPU 控制台项目与配套的 ServerBox 监控客户端。

当前上传内容位于 [`serverbox/`](serverbox/)，是基于开源 ServerBox 的定制源码：

- GPU 任务内的 H100 负载、显存和温度采集，并通过控制台资源注册表更新数据来源。
- 独立的账号线程占用卡片。
- Mac 休眠、唤醒和网络恢复后的 SSH 隧道重连。
- GPU 查询断开后的恢复状态显示。

开始修改、构建与接入，请阅读 [ServerBox 定制版说明](serverbox/README.gpu-console.md)。
上游与依赖版本记录在 [SOURCE.json](serverbox/SOURCE.json)，ServerBox 的
[AGPL-3.0 许可证](serverbox/LICENSE)和依赖各自的许可证均随源码保留。

这里包含客户端源码和采集适配脚本，不包含登录凭据或本地客户端数据库。
队列端查询自动重试需要配套部署控制台服务代码；此前的服务器端部署被共享文件系统
阻塞，上传源码本身不会启用它。完整原生 macOS 构建尚未在此次整理中执行。
