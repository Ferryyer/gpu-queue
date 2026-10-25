# 个人 GPU 任务台

网页、启动授权、队列顺序和调度服务都在本人服务器，日常使用不连接 chatgpt.site。代码快照、输入校验和逐步执行规则继续有效。

## macOS 桌面小面板

运行 `python3 scripts/package-widget.py` 生成 `~/results/gpuq-launcher/GPU任务台-桌面小组件-macOS.zip`。在 Mac 解压并双击“安装桌面小组件.command”，由系统自带 `osacompile` 将源码编译为 `~/Applications/GPU 任务台小组件.app`，使用本机临时签名，创建桌面入口，并启用登录 Mac 后自动打开。无需安装 Python、Node 或 Xcode。

已安装的小面板可直接双击新版包中的“开启开机自启动.command”；关闭用“关闭开机自启动.command”。自启动使用本人的 `~/Library/LaunchAgents/work.markflow.gpuqueue.widget.linlishuo.autostart.plist`，仅在图形桌面登录时打开一次应用，没有 KeepAlive，不会在手动退出后反复拉起。关闭自启动不退出面板、不停止服务器任务。卸载前先关闭自启动，再删除应用和桌面入口。自动打开只连接、显示状态，GPU 任务继续等待网页“开始”授权。实现依据见 [Apple LaunchAgent 说明](https://github.com/apple-oss-distributions/launchd/blob/main/man/launchd.plist.5)。

面板可拖动、记忆位置，默认位于普通窗口下方的桌面层，可勾选“置顶”。显示连接状态、运行/排队/待启动数量与当前任务；提供打开完整网页、连接/断开及选择 SSH 配置。SSH 在后台使用本人已有 agent/keychain 凭据；需要本人登录时，点“完成登录”才打开原启动器的登录窗口。面板读取共享的配置路径/端口偏好，不保存密码或私钥。

状态每约 5 秒从任务台读取，断开仅终止本面板创建的 SSH 子进程，不能关闭由其他窗口维护的连接；退出面板不停止服务器任务。HTTP 请求使用临时私有文件接收，避免大日志响应填满管道卡住窗口。连接状态模型测试覆盖身份核对、已有通道复用、端口冲突、登录回退、断开后的迟到响应与子进程归属。

从 1.1.0 起，面板有“检查更新”按钮，打开独立的更新窗口，显示当前版本、新版说明和下载/安装状态。启动时和每隔 6 小时检查公开 GitHub 更新信息；发现新版本只提示，由用户点击“下载并安装”。更新器核对版本、受信任下载地址、文件大小、SHA-256 和 ZIP 文件清单后，在本机编译并签名新版；准备好后才请求当前面板退出。独立更新器等待旧面板关闭，再替换和重开，保留旧版备份、SSH/位置/自启动偏好。更新器仅更新 Mac 客户端，不启动服务器 GPU 任务。进程识别按本人应用路径和 bundle ID，使用 [Apple NSRunningApplication](https://developer.apple.com/documentation/appkit/nsrunningapplication) 请求退出。

发布更新时，递增 `launchers/macos/widget/release.json` 的三段版本号并写更新说明，运行 `python3 scripts/package-widget.py`。将产出的 `~/results/gpuq-launcher/github-profile/` 下列文件在同一次提交中发布到 `Ferryyer/Ferryyer` 的 `main`：`downloads/GPU-Queue-Widget-<版本>-macOS.zip`、`downloads/GPU-Queue-Widget-macOS.zip`、`downloads/SHA256SUMS`、`updates/gpu-queue-widget.json`。每个已发布的版本文件保持不变，新内容须增加版本号；不要只推源代码而遗漏安装包和更新信息。`--output-dir` 可指定其他打包目录。首次从旧版升级需要下载并安装一次 1.1.0，之后即可通过更新窗口升级。

当前开发服务器为 Linux；已检查脚本语法并测试连接状态逻辑，Mac AppKit 窗口、原生编译与安装仍需首次在 Mac 上验证。原生实现使用 Apple AppKit 与 JavaScript for Automation，开发依据见 [Apple JXA 文档](https://devstreaming-cdn.apple.com/videos/wwdc/2014/306xxjtg7uz13v0/306/306_javascript_for_automation.pdf)。

小面板 1.1.1 同步采用暖纸色与衬线标题，支持模式按钮和面板获得键盘焦点时的 Shift+Tab 切换，保存 Edit / Auto 选择，并传给下次打开的网页。已打开的网页保持自己的模式；小组件切换不会启动任务。

### 安装包路径无效的修复（1.1.2）

旧更新器可能把 Info-ZIP 输出的中文路径转义当作无效路径。1.1.2 兼容该清单表示，并固定清单命令的 UTF-8 环境，继续执行严格路径白名单和校验和检查。若旧版本已出现此错误，请从 GitHub 下载新版 ZIP，完整解压后双击“安装桌面小组件.command”覆盖安装一次；旧更新器本身无法通过尚未通过的安装流程更新。保留 SSH、位置和自启动偏好。

## macOS 双击打开

运行 `python3 scripts/package-launcher.py` 生成 `~/results/gpuq-launcher/GPU任务台-macOS.zip`。解压后把“打开 GPU 任务台.command”放到 Mac 桌面，以后双击即可自动连接并打开浏览器。首次需要本人 SSH 登录时按提示完成；配置不在默认位置时选择已有的 config 文件，之后会记住路径。

连接窗口保持打开；关闭不会停止服务器任务。重复双击会复用已经连通的入口，本地端口占用时自动尝试 8791–8799。启动器保留现有 SSH 主机校验，只连接本人的远端网页 socket，不执行 GPU 申请或任务启动。

## 从电脑手动打开

使用已经能登录本人服务器的 SSH 配置。在电脑终端运行并保持窗口打开：

```sh
ssh -F ~/.ssh/markflow-linlishuo/config -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -L 127.0.0.1:8790:/tmp/gpuq-21005/web.sock markflow-cpu
```

然后打开 http://127.0.0.1:8790/ 。若本人 SSH 配置保存在其他位置，替换 `-F` 后的文件路径；使用已有的个人登录方式，无需上传私钥或配置网页密码。Windows PowerShell 可把配置路径写成 `$HOME/.ssh/markflow-linlishuo/config`。本地 8790 已占用时，可将转发参数中的 8790 改为 8791，并打开对应地址。

SSH 只负责网页连接，关闭连接不会停止已经启动的任务。服务器恢复后由个人服务监管器重启网页和队列服务，浏览器刷新即可重新连接。断线不会把失败步骤重新运行。

## 网页操作模式

网页采用暖纸色背景、衬线标题与系统界面字体；全部使用本机字体，无需外部字体连接。顶部模式按钮或 **Shift+Tab** 可切换：

- **Edit mode**：手动启动准备好的任务、拖动或用方向键调整已授权队列顺序。
- **Auto mode**：监看已授权任务按现有调度规则自动执行，锁定启动和排序；日志、结果和停止入口继续可用。切换模式不会批准新任务或改变后台调度策略。

模式选择保存在当前浏览器，刷新后保留。输入框、可编辑区域和弹窗内保留 Shift+Tab 的原生焦点导航。停止任务的确认流程在两个模式下均有效。

## 提交与执行

```sh
gpuq validate --manifest /绝对路径/task.json
gpuq submit --manifest /绝对路径/task.json --source Codex
# Claude 使用 --source Claude
gpuq status
gpuq doctor
```

提交不申请 GPU。用户在网页对固定版本点击“开始”后，调度服务才会申请或复用资源。多步任务顺序执行、失败即停；已批准且尚未投放的任务可拖动排序。持续低占用、显存充足且资源兼容时，最多并行两个任务。预计小时只是申请规划，任务不会因此被本服务定时终止；平台回收规则仍适用。

## 服务与数据

### 已点击开始却没有新申请

`gpuq-submit` 负责固定任务并入队，`markflow-gpu` 的表单适配器由 CPU 调度服务调用；skill 本身不向运行中的服务发送启动命令。先用 `gpuq status <任务编号>` 核对授权时间、申请 UUID 与 `phase`。没有新 UUID 且提示“旧申请的可用状态待核查”，表示旧资源尚未确认终止，服务为避免重复占卡暂停新增申请。任务历史完成或只读探测超时不能作为实例已回收的证据；需要匹配旧 UUID 的平台终止通知或用户确认。

旧启动通知只消费一次，不能把探测超时的实例重新标成就绪。表单提交超时保留同一 UUID 与 `submission_unknown`，网页显示“提交回执待核查”，不能当作已受理；不生成新 UUID 重试。服务每轮结束同步真实错误与任务阶段，查询飞书失败也会显示在网页。测试 `tests/test_request_diagnostics.py` 覆盖这些路径，所有平台写入均为隔离模拟。

- `gpuq`：CPU 调度服务；`gpuq-web`：网页服务，均由 `mf-services` 管理。
- 私有网页 socket：`/tmp/gpuq-21005/web.sock`，所属目录 0700、socket 0600；不监听公网 TCP。
- 持久任务库：`~/.local/state/gpuq/queue.sqlite3`。`tasks` 保存固定任务，`controls` 独立保存启动授权、顺序和领取状态，`queue_audit` 记录网页决策。排序与领取通过 SQLite 事务和队列版本防止竞争。
- 日志：`~/.local/state/markflow-services/gpuq.log` 和 `gpuq-web.log`。
- 配置：`~/.config/gpuq/connection.json`，只需本人身份和平台工具路径；没有 Sites 凭据。
- 迁移前数据库一致性备份与最后一份云端控制记录保存在 `~/.local/state/gpuq/migration-backup-20261023/`，保持私有。迁移只导入一次，不覆盖之后的网页决策。

旧 Sites 入口已停用网页启动/排序；`worker/` 与 D1 代码仅保留为旧发布记录。新网页没有远程字体或外部网页依赖。浏览器的写操作校验本地 Host、同源 Origin 和操作标记；提交、调度领取接口不对网页开放。不要将本地转发改为监听所有网卡。

## 验证

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/cloud.test.js
```

`tests/local_python_server.py` 使用隔离的临时数据库和真实本地网页处理器，供 `tests/browser_check.py` 验证桌面拖动、触摸拖动、启动持久化、日志和失败进度；不启动调度器、不申请 GPU。

## 用完释放的偏好

用户要求队列用完即释放本人新申请的卡。当前成员工具 `mf-gpu` 仅支持提交/状态/执行，GPU申请表也没有主动释放入口；因此本服务尚不能执行实例释放，不会把任务完成或连接超时报告为已释放。网页持续显示这个限制；已启动的队列结束后，服务器在 `~/.local/state/gpuq/release-intents/` 记录待释放请求，待平台提供普通成员释放接口后接通。平台仍按空闲和最长存活规则回收。

仅记录本服务新申请资源的释放意图；复用的其他资源不自动处理。排队中、执行状态未知或提交回执不明时，不将队列视为已用完。未点击开始的准备任务不占用释放等待。

## 显存单位

任务 `resources.memory_gb` 使用十进制 GB（1 GB = 10^9 字节），`nvidia-smi` 的数值使用 MiB，调度时先换算再比较。串行任务额外预留 2 GiB；增加并行时额外预留至少 2 GiB 或整卡 10%（取大值），同时继续检查已有进程、持续低占用及并行数量。单卡 80 GB 的任务可在空闲 H100 80GB（实测 81559 MiB）上通过串行资源检查，空闲不足时仍等待。

## ServerBox 自动同步

任务服务将已发现的本人实例生命周期和只读 GPU 查询结果写入
`~/.local/state/serverbox-gpu/registry.json`（原子更新，0600）。ServerBox
继续使用同一个 CPU SSH 入口；实例申请编号、主机和 GPU 型号变化由注册表传递，
不需要改 Mac 上的连接地址。新实例就绪后的现有探测会同时采集负载、显存、温度
和 GPU 端的真实采样时间，通常约 30–45 秒刷新一次，不新增常驻 GPU 采集任务。

任务队列空闲后仍检查已发现实例的状态，平台确认回收或关闭后同步清除实时读数。
通知最多每 60 秒检查一次；网络和平台延迟可能延长同步时间。执行或查询超时只
标记状态未知，不宣称实例已销毁。待释放意图仍表示“尚未确认销毁”。新采样超过
90 秒不再供 ServerBox 显示为实时；CPU 端重写注册表不会刷新 GPU 采样时间。

Mac 的 `serverbox-gpu-status` helper 需要支持此注册表协议。注册表存在后它具有
优先权，不会回退到旧申请的独立采集文件。此同步不会创建申请、授权模型任务、
自动重跑失败任务或调用尚不存在的销毁接口；网页“开始”仍是计算启动入口。

## 停止任务

网页任务详情提供“停止任务”或“移出队列”，确认后通过 `POST /api/tasks/<任务ID>/stop` 提交当前固定版本的 `digest`。请求继续检查同源 Origin 与操作标记；CLI 没有启动或停止授权命令。

- 未投放任务立即取消、移出执行队列，陈旧领取请求不能把它启动。
- 已投放任务先显示“正在停止”，已有产物与日志保留。确认本任务的进程及子进程退出后才显示“已停止”；未确认或 GPU 无响应时持续显示待核查，不报告停止成功。再次运行需提交新版本并由用户重新启动。
- 新投放任务由独立控制层监督，不修改已批准的计算代码或冻结 runner；停止标记可在执行入口启动前阻止计算，也可停止运行中的步骤。
- 兼容升级前已运行的任务：在原申请上提交一次控制命令，核对原 job、命令行、UID、启动时间及任务环境标记，再用 pidfd 定向停止进程树。普通终止无效时结束残留进程；不使用用户级广泛匹配或整张卡的进程组停止。旧入口可能要等待一次 GPU 队列轮询后才处理。
- 停止任务不等于释放实例，也不能撤回已在途的 GPU 申请。进程退出证据与资源释放回执分开；平台主动释放接口仍未开放。

测试使用隔离目录和 CPU 假进程验证进程树终止、无关进程保留、产物保留、版本/来源校验、队列竞争与停止确认，不用真实 GPU 任务做取消测试。
