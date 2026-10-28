# MF-12 · 统一工作台工程与验收

本分支基于 PR #1 的 `6a0b990`，提供 ServerBox 内的原生任务工作台，替换原有外部浏览器入口。当前为工程候选版 `2.0.2000+2000`；没有生产部署、发布 Release 或生成已验收的 Mac 安装包。

## 应用内流程

主导航优先呈现总览、任务、服务器；设置继续固定在导航末尾。既有自定义页签保留在后面或「更多」，终端、文件、进程、GPU 与原有工具仍可进入。

1. 在「服务器」添加或导入原有 SSH 配置，在任务页或设置的任务服务入口选择运行 gpuq 的那台服务器。
2. 点击「连接 / 重试」。应用复用 `serverProvider(id).ensureShellClient()` 的 SSH 会话、认证、主机密钥验证和重连限制；轮询仅使用现有连接，不另开 SSH 登录或 HTTP 隧道。
3. 任务页原生展示列表、筛选、详情、队列排序、步骤日志、结果、检查与事件。手机点击任务进入独立详情路由；返回保留列表上下文。桌面列表与详情并排，完整监控默认折叠。
4. 执行端同步任务的 `execution.instance_id`、`job_id`、`workspace`、`host`。旧任务服务只有 `request_uuid` 时仍可关联实例，但没有可靠工作目录时文件按钮禁用。
5. 在任务详情显式关联该实例实际所属的已有 SSH 配置。应用不按主机名、任务名或当前选中服务器猜测目标。关联按「任务服务 ID + 实例 ID」隔离，并校验两端 SSH 的地址、用户、端口、跳板与代理配置摘要；修改连接目标后需要重新关联。
6. 「服务器 / GPU」「SSH 终端」「工作目录 / SFTP」都在当前应用的导航栈打开。返回回到原任务；服务器详情的 Inspire Queue 操作反向列出已明确关联该服务器的任务。结果文件也使用该关联服务器。

任务目录来自执行端，路径仅用于打开对应服务器；终端 `cd` 使用单引号转义，任务内容不能形成 shell 参数。不同实例即使同名也不会自动复用关联。

## 权限与连接

原生桥接使用已认证 SSH 的 exec channel，在远端通过 Python 标准库访问 `/tmp/gpuq-<uid>/web.sock`。不新增监听端口或常驻服务，不安装远端代码，不读取或复制任何登录凭据。服务端保留原有 Host/Origin、动作头、digest、revision 与停止控制检查。

只支持既有的 state/health/start/stop/reorder 入口。提交任务继续使用 `gpuq submit`；提交本身不授权。只有用户点「开始这一版任务」才调用 start。Edit/Auto、轮询、重连和切换服务器不批准任务。Auto 阻止启动与排序，仍允许用户确认停止。HTTP/SSH 写入回执丢失时不重放动作，要求刷新核对结果。

SSH、任务服务和 GPU 采样分别显示状态。任务服务失败不改变整台机器的 SSH 状态；保留历史快照并标为非实时。GPU 样本要求在线、时间不超前 5 秒且不超过 90 秒。更换服务地址后拒收旧响应，并在新读成功前阻止旧快照上的操作。

模式偏好和服务/实例关联保存在现有应用设置存储，凭据继续留在原加密服务器与钥匙存储。没有修改原 SSH 配置、密钥、已批准队列或后台 GPU 调度策略。

## 小组件、安装与更新

统一版使用应用内现有的原生菜单栏/托盘作为摘要与入口，复用同一批服务器 provider；点击打开进入任务页，没有第二套连接或更新进程。

旧 `launchers/macos/widget/` 是兼容维护的独立旧产品，ZIP 与旧主页更新地址均未改动。旧小组件不会被伪装成统一版。实际迁移时先退出旧小组件并在旧组件内关闭其自启动，再启用统一应用的菜单栏常驻；不删除 SSH 偏好、钥匙串或旧组件安装目录。

原生应用更新源改为 `Ferryyer/gpu-queue` Releases，不能回退安装上游 ServerBox/App Store 二进制。候选版本为 `2.0.2000+2000`，匹配现有更新器的发布标签为 `v2.0.2000`。统一包名 `GPU-Queue-macos-<arm64|x86_64>-2000.dmg`，`-unsigned` 仅供 QA，更新器不选取。

完整构建前依照 `serverbox/README.gpu-console.md` 准备指定提交的 IronRDP、Flutter、Xcode、Rust。保留当前用户实际使用的数据/钥匙串定义；下面沿用源码快照已有的 H100 配置，不能换定义后声称保留了原配置：

```sh
cd serverbox
flutter pub get --enforce-lockfile
flutter build macos --release \
  --dart-define=SERVERBOX_DATA_NAME=ServerBoxH100 \
  --dart-define=FL_LIB_MACOS_DATA_PROTECTION_KEYCHAIN=false \
  --dart-define=FL_LIB_MACOS_SECURE_ACCOUNT=local.ferry.serverbox.h100
cd ..
python3 scripts/package_unified_macos.py --app 'serverbox/build/macos/Build/Products/Release/Inspire Queue.app'
```

打包器先核验 Info.plist 版本、bundle ID 和可执行文件。正式候选要求 `codesign --verify --deep --strict` 与 `spctl --assess` 成功，再生成 DMG、`SHA256SUMS`、`unified-release.json`。没有真实 Mac app 时不能产出所谓正式包；`--inspect-only` 只检查元数据，`--allow-unsigned` 明确生成不进入更新选择的 QA 包。

正式分发前在 Mac 上验证 SHA-256、挂载 DMG、覆盖安装、钥匙串/SSH 配置保留和下次更新。不要变更 bundle ID 来绕过现有身份，也不要复用上游签名身份。发布签名和公证由拥有者实际可用的开发者环境提供。

## 本轮验证与边界

- Flutter 3.47.8 / Dart 3.13.7 已准备，`flutter pub get --enforce-lockfile` 成功。
- `dart analyze lib test/unit/app/queue_protocol_test.dart test/unit/app/queue_session_test.dart` 通过。修复了 PR #1 暖纸色函数混用 Flutter Material 与项目 `material_ui` ThemeData 的编译错误。
- 11 项生产 Dart 协议/会话测试通过；使用 `python3 scripts/test_queue_dart.py --flutter <flutter绝对路径>` 可在无原生 C/Rust 工具链环境重现。隔离的是不相关构建 hook，测试导入的是本仓库真实生产源文件，不是测试替身。
- 65 项 Python 测试、32 项 Node 测试、14 项 GPU 桥接和 6 项线程采样测试通过。新增原生 Python 桥接测试使用隔离 Unix socket 和无调度器的临时任务库，不触及真实用户任务。
- 打包元数据校验覆盖空格/中文目录、错误版本和非法可执行文件路径；这不是 Mac 实机安装测试。
- Chromium 使用 CPU fixture 验证两轮 5 秒刷新后焦点仍在原控件且 Enter 可继续排序、断线与恢复、GPU 缓存非实时、320/390/640/800/1024/1440px 布局、手机独立详情返回、真实时间比例趋势与采样点。截图只证明网页模块，不证明 Flutter/macOS 通过。

初轮阻塞：完整 `flutter test` 在 `flutter_pty` 的 native build hook 报 `No compiler configured on host linux_x64`。后续已准备任务内 Clang/Rust/IronRDP 并解除 PTY 编译问题，又修复旧动态库加载与 code-asset 映射不兼容；真实 PTY hook 与 3 项本地终端测试已通过。原生接手步骤和 CI 通道见 [Mac 验收接手包](MAC-NATIVE-HANDOFF.md)，最新整应用构建结果以任务本轮证据为准。根目录全量分析还会扫描未独立 pub get 的 vendored example；应用 lib 定向分析已无问题。当前运行时没有 Mac/Xcode，原生 SSH/SFTP 实机闭环、中文字体/深浅色/全屏、Swift 重连与签名安装更新仍需 Mac 验收。没有申请 GPU，也没有启动真实用户任务。

## Mac 必须补齐的验收

使用已有测试 SSH 服务器和隔离任务服务，在同一个窗口完成：任务 → 明确关联的 GPU/服务器 → 终端 → 返回 → SFTP 工作目录 → 返回结果。两台服务器轮流选择，核对 terminal/SFTP 的目标、路径和实例，修改服务器地址后原关联必须失效。

同时验收 SSH 成功/任务服务失败、无权限、断线重连、空任务/空实例、停止取消与确认、启动 digest 冲突和回执丢失不重放；连续两轮刷新保持焦点、选中项和滚动位置。最后检查原生中文字体、深浅色、Safari 网页缩放/全屏以及真实安装更新与旧版配置保留。上述项目通过前，本分支不代表已交付可安装的统一桌面版。

## MF-9 复验修正（2026-10-24）

- 窄屏网页详情具备命名 `dialog` 语义、`aria-modal` 与背景 `inert` 隔离。Tab / Shift+Tab 在详情内循环，模态内不触发模式快捷键；Esc 或返回按钮恢复原任务焦点与页面滚动。切回桌面宽度时解除隔离。详情内的停止确认框保留自己的焦点循环，轮询和详情页签切换后恢复控件与详情滚动。
- 原生任务详情在启动按钮**之前**独立展示「申请资源需求」、GPU 数量、每卡 GB 显存和固定版本；未知值显示「未提供」。申请需求与下方实际 GPU 实例分开。既有 Auto / 断线禁止启动逻辑保持。
- 原生监控及任务内 GPU 卡共用 `QueueResourceView`：逐卡利用率、显存已用/总量 GiB、温度 °C；缺测显示破折号，过期、离线或断线不显示缓存指标。采样时间以相对时间呈现，tooltip 和主动打开的诊断框可查看绝对时间。JSON 仅在诊断框展开后出现；步骤状态转换为中文语义。

此次复跑结果：65 项 Python、32 项 Node、19 项 Dart/Flutter 隔离测试通过，应用 `lib` 与新增测试定向 `dart analyze` 无问题，网页构建通过。19 项包含原 11 项协议/会话、6 项呈现边界和 2 项真实监控组件的 Flutter CPU 渲染/弹窗测试。通过以下命令重现：

```sh
node scripts/build.mjs
node --test tests/cloud.test.js tests/monitor.test.js tests/modes.test.cjs tests/widget.test.cjs tests/widget-update.test.cjs
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/test_queue_dart.py --widgets --flutter <flutter可执行文件>
cd serverbox
dart analyze lib test/unit/app/queue_presentation_test.dart test/unit/app/queue_resource_widget_test.dart
```

隔离测试直接导入真实生产源文件，仅构建 Flutter 和锁定版本的 UI 依赖，不构建 SSH/PTY/Rust 应用；不能据此声称完整原生应用构建通过。再次尝试应用本身的 `flutter test --no-pub test/unit/app/queue_protocol_test.dart test/unit/app/queue_session_test.dart test/unit/app/queue_presentation_test.dart test/unit/app/queue_resource_widget_test.dart`，仍在 `flutter_pty` hook 报 `No compiler configured on host linux_x64`。

Chromium 的 `tests/browser_unified_check.py` 已覆盖 390/640/800px 下完整正反向 Tab 顺序、各两轮 5 秒轮询、详情/列表滚动与任务焦点恢复、停止确认框、桌面尺寸切换及无意授权检查；保留此前 320–1440px 布局、排序和断线恢复检查。`tests/browser_monitor_check.py` 也通过。输出证据在 `build/unified/checks.json` 与截图，由任务评论以附件交付，全部为隔离 fixture。Mac、Safari、Swift 重连、SSH/SFTP 实机闭环和安装更新门槛仍待具备相应环境后完成；本次没有发布安装包、合并或生产部署。

## PR 关系

本 PR 以 `codex/gpu-serverbox-integration` 为 base，只展示 MF-12 增量。先处理并合并 PR #1，再将本 PR 改 base 到 main、复核差异及构建。不覆盖 PR #1 的任何提交，不合并、不生产部署，也不改变 MF-7 隔离验收产物。
