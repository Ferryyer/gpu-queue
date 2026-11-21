# 单向历独立更新

员工版随应用包含 `UpdateDailyCalendar` 脚本和 `CalendarCheck` 本机日期校验器。不读取 Codex 任务、不需要 Codex、Python、Xcode、账号授权或后台服务。

应用启动、回到前台时检查缓存；当天已更新则直接复用同一张图片。保持打开时按北京时间次日 00:01 检查，失败每 30 分钟重试，也可点刷新立即重试。退出应用后不常驻，下次打开自动补更。

缓存位于应用数据目录的 `daily-calendar/`，按图面日期保存图片、原图链接和同日出处笔记。应用不会写桌面文件。出处笔记从当前仓库 main 分支的 `calendar/notes/YYYY-MM-DD.md` 读取，严格校验文件日期；未发布时每半小时重试，已有笔记可离线阅读，手动刷新可获取修订。更新笔记不会重载图片。

维护者本机的每日任务负责研究、核对并运行 `scripts/publish_calendar_notes.py` 上传公开笔记。同事只读取公开 GitHub 内容，不需要 Codex、GitHub 登录或上传权限。维护者任务未运行不会阻止日历下载；今日笔记不可用时保留原图来源，不借用其他日期的解读。

脚本通过 HTTPS 下载单向空间图片，保留证书校验、超时和大小限制。来源有时将图片放在次日文件名下，因此依次检查当日、次日两个地址，使用 macOS Vision 在本机核对图面月份、日期和年份后才原子写入缓存。图片日期不符、无法识别、网络异常时保留原缓存；不把下载时间当作图片日期。图片解析与识别不会上传数据。

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
