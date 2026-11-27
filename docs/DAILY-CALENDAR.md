# 单向历独立更新

员工版随应用包含 `UpdateDailyCalendar` 脚本和 `CalendarCheck` 本机日期校验器。不读取 Codex 任务、不需要 Codex、Python、Xcode、账号授权或后台服务。

应用启动、回到前台、重新进入总览时先显示可用缓存，再实际检查上游图片，即使已有当天缓存也检查同日修订。点刷新立即检查，不受当天缓存或失败冷却限制；检查过程中仍可点击，连续请求合并为一次后续检查，写入串行执行。跨北京时间零点的请求完成前会补查新日期，旧请求不能在新请求之后覆盖结果。保持打开时按北京时间次日 00:01 检查，失败每 30 分钟重试。退出应用后不常驻，下次打开自动补更。

缓存位于应用数据目录的 `daily-calendar/`，按图面日期保存图片、原图链接和同日出处笔记。新图片以 `YYYY-MM-DD.<SHA256>.jpg` 保存，用原子替换的 `YYYY-MM-DD.json` 同时记录日期、校验和、原图链接；读取时复核校验和，避免将同日新图与旧来源配对。保留旧版日期文件的读取兼容，已有个人数据无需迁移。应用不会写桌面文件。出处笔记从当前仓库 main 分支的 `calendar/notes/YYYY-MM-DD.md` 读取，严格校验文件日期及其声明的图片 SHA-256；只有匹配当前图片字节的笔记才作为出处显示。缺少图片标识的旧笔记仍保留文件，但不再直接作为当前图片的出处。同日换图后，即使网络继续返回上一张图的笔记，也会保留当前清单的原图来源并提示笔记尚不可用，直至发布匹配的新笔记。每半小时重试，匹配的笔记可离线阅读，手动刷新可获取修订。仅更新笔记时复用相同图片字节。

维护者本机的每日任务负责研究、核对并运行 `scripts/publish_calendar_notes.py` 上传公开笔记。同事只读取公开 GitHub 内容，不需要 Codex、GitHub 登录或上传权限。维护者任务未运行不会阻止日历下载；今日笔记不可用时保留原图来源，不借用其他日期的解读。

脚本通过 HTTPS 下载单向空间图片，保留证书校验、超时和大小限制。来源有时将图片放在次日文件名下，因此依次检查当日、次日两个地址，使用 macOS Vision 在本机核对图面月份、日期和年份后才原子写入缓存。图片日期不符、无法识别、网络异常时保留原缓存；不把下载时间当作图片日期。图片解析与识别不会上传数据。

如需手动运行，安装应用后执行（目录可自行指定）：

```sh
/bin/bash '/Applications/Inspire Queue.app/Contents/Helpers/UpdateDailyCalendar' "$HOME/Library/Caches/InspireQueueCalendar"
```

脚本源码：`scripts/update_daily_calendar.sh`；校验器源码：`serverbox/macos/CalendarCheck/main.swift`。发布包在构建时编译并签入校验器，同事无需编译。

检查失败时，即使缓存属于今天也会提示尚未取得最新内容，避免把缓存当成本次更新成功。上游若改变图片版式，日期验证可能拒绝更新；应用会继续显示带日期的旧图，等待兼容更新。当前仅提供 Mac 版。

## 验证

`python3 scripts/test_queue_dart.py --calendar` 在隔离 Flutter 测试环境运行生产缓存、更新器和界面测试；`python3 -m unittest discover -s tests -p test_calendar_refresh_script.py` 使用合成数据验证脚本下载及原子发布流程，不代表 OCR 验证。macOS 的 `python3 scripts/test_daily_calendar.py` 使用真实 Apple Vision 核验合成图片日期和同日修订，已纳入既有 `employee-release.yml`；完整构建及日历界面测试沿用该流水线的 `scripts/native_acceptance.py`。Linux 无法验证 Apple Vision、签名和原生构建，须以对应候选提交的 Mac 流水线及试用结果为准。

## 发布出处笔记

固定目录：[calendar/notes](https://github.com/Ferryyer/gpu-queue/tree/main/calendar/notes)。只发布可公开的出处资料，不上传个人配置或聊天记录。

每篇第一行是 `<!-- inspire-calendar-date: YYYY-MM-DD -->`。供应用显示的笔记第二行必须是 `<!-- inspire-calendar-image-sha256: 64位小写十六进制摘要 -->`，摘要来自维护者实际核对的原始图片字节（可用 `shasum -a 256 /path/to/reviewed-image.jpg` 计算）；正文包含出处、置信度和 HTTPS 阅读链接。发布器兼容校验旧日期格式，但应用不会展示没有图片标识的旧笔记。仅修改同一张图片的笔记正文时保留该摘要；换图后须重新核对内容并更新摘要，不能把新下载图片的摘要自动套给旧笔记。先核查内容，再运行：

```sh
python3 scripts/publish_calendar_notes.py --date YYYY-MM-DD --file /path/to/reviewed-note.md --check
python3 scripts/publish_calendar_notes.py --date YYYY-MM-DD --file /path/to/reviewed-note.md
```

发布器使用维护者已有的 `gh` 登录，凭据不会写入应用。重复发布同内容不产生新提交；修改内容时核对现有文件 SHA，完成后读取 Git blob 验证字节。
