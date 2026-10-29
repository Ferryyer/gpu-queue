# 单向历独立更新

员工版随应用包含 `UpdateDailyCalendar` 脚本和 `CalendarCheck` 本机日期校验器。不读取 Codex 任务、不需要 Codex、Python、Xcode、账号授权或后台服务。

应用启动、回到前台时检查缓存；当天已更新则直接复用同一张图片。保持打开时按北京时间次日 00:01 检查，失败每 30 分钟重试，也可点刷新立即重试。退出应用后不常驻，下次打开自动补更。

缓存位于应用数据目录的 `daily-calendar/`，按图面日期保存 `YYYY-MM-DD.jpg` 和同日来源链接。不会写桌面文件，也不依赖个人的桌面笔记。读不到今日图片时保留最近有效缓存并明确标出日期。出处按钮显示原图链接，作者、作品以图面署名为准，不自动生成 AI 文学解读。

脚本通过 HTTPS 下载单向空间图片，保留证书校验、超时和大小限制。来源有时将图片放在次日文件名下，因此依次检查当日、次日两个地址，使用 macOS Vision 在本机核对图面月份、日期和年份后才原子写入缓存。图片日期不符、无法识别、网络异常时保留原缓存；不把下载时间当作图片日期。图片解析与识别不会上传数据。

如需手动运行，安装应用后执行（目录可自行指定）：

```sh
/bin/bash '/Applications/Inspire Queue.app/Contents/Helpers/UpdateDailyCalendar' "$HOME/Library/Caches/InspireQueueCalendar"
```

脚本源码：`scripts/update_daily_calendar.sh`；校验器源码：`serverbox/macos/CalendarCheck/main.swift`。发布包在构建时编译并签入校验器，同事无需编译。

上游若改变图片版式，日期验证可能拒绝更新；应用会继续显示带日期的旧图，等待兼容更新。当前仅提供 Mac 版。
