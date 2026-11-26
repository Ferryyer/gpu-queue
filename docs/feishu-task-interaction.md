飞书任务交互（LS-51）

概览内嵌页与完整任务页共用 `serverbox/assets/feishu/inspire-task.user.js`。

- 完整任务页的首次登录提示在 6 秒后自动收起，也可立即手动关闭；概览不显示这条提示。
- 飞书“想要更好的飞书网页版体验 / 试试这些浏览器吧”推荐条先尝试自身关闭按钮，最多三次。缺少按钮或按钮不响应时，仅隐藏已识别的推荐条；关闭主题美化后仍生效。登录页、其他提示和任务内容保持正常。
- 任务根节点尺寸改变、异步替换、网页视觉视口缩放后，在布局完成后合并发送一次 `resize`，让网页重新计算布局。
- “页面选项 → 隐藏网页悬停提示”默认开启，控制鼠标触发的 `role=tooltip` 浮层。任一内嵌页改变选项后，另一个页面同步更新；应用重启保留选择。键盘操作恢复说明的可见性。此开关不处理任务行高亮、浏览器原生 `title` 提示或点击偏移。
- 在浏览器使用时，可将同一 `.user.js` 安装到油猴；其菜单也可切换悬停提示，偏好保存在油猴中，与应用的本机偏好独立。

验证命令：

```sh
npm ci --prefix scripts/feishu-tests --no-audit --no-fund
node --test scripts/feishu-tests/style.test.cjs
python3 scripts/test_feishu_pointer.py  # 需 Playwright 与 Chromium
cd serverbox
flutter test test/unit/app/feishu_task_widget_test.dart test/unit/app/overview_layout_test.dart
cd ..
python3 scripts/test_feishu_browser.py  # 需 macOS、Xcode、WebKit；已接入 native_acceptance.py
```

浏览器检查使用完全拦截的合成页面，覆盖两种布局、520/1200 宽度、80%/100%/125%/150%/200% CSS 缩放及 DPR 1/2，检查实际鼠标移动、点击命中、推荐条关闭、错误保留与提示切换。它不能证明已登录飞书或 Flutter/AppKit 的原生鼠标转发在所有缩放率下均正确。

PR 的 `Feishu task interaction` CI 自动运行脚本测试、Chromium 合成页面检查及 macOS Swift/WebKit 检查。WebKit 检查编译生产视图，仅替换 Flutter 消息通道；不构建完整应用，也不替代 Flutter widget tests 或真实登录后的人工验收。

Mac 交付验收需在真实应用中：

1. 依次打开概览和飞书任务页，检查推荐条消失、登录提示自动收起，以及刷新、路由切换后行为。
2. 在实际使用的缩放率、外接屏和窗口尺寸下，逐项检查任务行悬停、打开任务、勾选完成、编辑与滚动；确认指针和操作目标一致。
3. 在任一页面切换隐藏悬停提示，确认另一页同步、重启后保留，键盘导航仍能查看说明。
4. 若仍存在原生点击偏移，记录界面、缩放率和具体控件，交回定位；隐藏浮层只作为视觉兜底。

回退：取消勾选“隐藏网页悬停提示”可立即恢复浮层。代码回退应只反向应用 LS-51 的 diff，保留后续其他改动；浏览器端可停用或卸载脚本。
