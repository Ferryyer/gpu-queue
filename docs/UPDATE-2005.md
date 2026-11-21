GPU Queue 2.0.2005 修复应用内更新出现 `invalid_update / 无效的更新信息`。

2.0.2004 的 `CFBundleVersion` 为 2004，但发布流程绕过 fl_build，遗留的 Dart `BuildData.build` 仍为 2001。界面因此再次提供 2004，下载完成后原生安装器正确拒绝安装相同版本。

新版从 `serverbox/pubspec.yaml` 生成 Dart 版本。调整版本后执行 `python3 scripts/sync_app_version.py`；原生构建与打包均检查生成文件，发现版本不一致便停止。安装开始前还会读取正在运行的原生包版本，相同或更旧版本直接提示无需更新，不下载 DMG。原生安装器继续独立阻止重复安装与降级，界面展示可读错误，完整错误写入日志。

已安装 2.0.2004 的用户可以在新版发布后重新检查更新，选择 2005；旧安装器允许安装更高 build。也可下载新版 DMG，退出旧应用后拖入 Applications 覆盖。无需删除 SSH 配置或应用数据。旧 Widget 更新地址不变。

发布仍适用于 Apple Silicon、macOS 13+，使用 ad-hoc 签名，未公证。原生编译与临时应用覆盖、重启、回滚测试由 Mac 发布工作流执行；完整应用的人工安装与 SSH/SFTP 验收仍需实机完成。
