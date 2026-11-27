# 单向历独立更新

员工版随应用包含 `UpdateDailyCalendar` 脚本和 `CalendarCheck` 本机日期校验器。不读取 Codex 任务、不需要 Codex、Python、Xcode、账号授权或后台服务。

应用启动、重新进入总览和回到前台时先显示可用缓存，再实际检查上游图片；已有今日缓存也会重新下载核验同日修订。保持打开时每 30 分钟检查，并在北京时间次日 00:01 补查。手动刷新绕过重试间隔，刷新中再次点击会合并安排一次后续检查。请求串行执行，跨午夜的请求完成后立即检查新一天。退出应用后不常驻，下次打开自动补更。

界面始终标明图面日期。网络失败、上游未发布或日期验证不通过时，保留原有内容并明确提示本次尚未确认最新内容；已有今日图也不会掩盖本次失败。

缓存位于应用数据目录的 `daily-calendar/`。图片和原图链接先写入完整的不可变修订目录，再原子切换 `YYYY-MM-DD.current` 指针，避免图与来源混用。同日图片修订也会替换显示；未变图片保留原修订及已缓存的出处笔记。旧版按日期保存的缓存仍可读取，不改写个人数据。应用不会写桌面文件。出处笔记从当前仓库 main 分支的 `calendar/notes/YYYY-MM-DD.md` 读取，严格校验文件日期；未发布时每半小时重试，已有笔记可离线阅读，手动刷新可获取修订。更新笔记不会重载相同图片字节。笔记保存在对应图片修订中，新图片不会继承旧修订的笔记；公开笔记本身按日期发布，只能验证日期，不能证明其已经跟随上游同日修订。

维护者本机的每日任务负责研究、核对并运行 `scripts/publish_calendar_notes.py` 上传公开笔记。同事只读取公开 GitHub 内容，不需要 Codex、GitHub 登录或上传权限。维护者任务未运行不会阻止日历下载；今日笔记不可用时保留原图来源，不借用其他日期的解读。

脚本通过 HTTPS 下载单向空间图片，保留证书校验、超时和大小限制；使用唯一查询参数和 no-cache 请求头避免复用旧的 HTTP 缓存，来源笔记保留原始公开地址。图片没有上游公开校验和，真实性依靠 HTTPS 与本机图面日期核验。应用共用一个更新器串行调用脚本；手动命令应在应用退出后执行。来源有时将图片放在次日文件名下，因此依次检查当日、次日两个地址，使用 macOS Vision 在本机核对图面月份、日期和年份后才原子写入缓存。图片日期不符、无法识别、网络异常时保留原缓存；不把下载时间当作图片日期。图片解析与识别不会上传数据。

如需手动运行，安装应用后执行（目录可自行指定）：

```sh
/bin/bash '/Applications/Inspire Queue.app/Contents/Helpers/UpdateDailyCalendar' "$HOME/Library/Caches/InspireQueueCalendar"
```

脚本源码：`scripts/update_daily_calendar.sh`；校验器源码：`serverbox/macos/CalendarCheck/main.swift`。发布包在构建时编译并签入校验器，同事无需编译。

上游若改变图片版式，日期验证可能拒绝更新；应用会继续显示带日期的旧图，等待兼容更新。当前仅提供 Mac 版。

## 发布出处笔记

固定目录：[calendar/notes](https://github.com/Ferryyer/gpu-queue/tree/main/calendar/notes)。只发布可公开的出处资料，不上传个人配置或聊天记录。

每篇第一行是 `<!-- inspire-calendar-date: YYYY-MM-DD -->`，正文包含出处、置信度和 HTTPS 阅读链接。先核查内容，再运行：

```sh
python3 scripts/publish_calendar_notes.py --date YYYY-MM-DD --file /path/to/reviewed-note.md --check
python3 scripts/publish_calendar_notes.py --date YYYY-MM-DD --file /path/to/reviewed-note.md
```

发布器使用维护者已有的 `gh` 登录，凭据不会写入应用。重复发布同内容不产生新提交；修改内容时核对现有文件 SHA，完成后读取 Git blob 验证字节。

## 相关验证

CPU 核心行为（无需 Flutter 或本机应用构建依赖）：

```sh
python3 scripts/test_calendar_dart.py --dart /path/to/dart
python3 scripts/test_daily_calendar.py -v
```

Flutter 面板行为（CPU 测试引擎，含打开、前台恢复、重入、刷新中再次点击和失败提示）：

```sh
python3 scripts/test_calendar_dart.py --flutter /path/to/flutter
```

`test_daily_calendar.py` 在 Linux 运行隔离的脚本协议样本，明确替换网络、系统日期/文件大小接口和 OCR 边界；不声称验证了 Apple Vision。在 macOS 另外运行真实 Vision 合成图片验证。完整 macOS 构建及原生校验由既有 `employee-release.yml` 候选构建流程执行；Linux 测试不替代这些证据。
