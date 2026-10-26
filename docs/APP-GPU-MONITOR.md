# App GPU 占用监测

本次修改 Flutter 桌面 App。总览和任务页的「GPU 占用监测」默认展开，展示当前资源，已结束资源单独折叠。卡的名称、容量和 UUID 来自真实采样，支持 H100、A100、4090 等 NVIDIA 型号及多卡混合，不依据旧连接名称固定型号。当前采样接口使用 `nvidia-smi`，未增加 AMD/Intel 采集器。

每张卡展示利用率、显存（GiB）、温度、UUID 与采样时间。缺失指标显示“—”，真实空闲保留 0%。资源失联或超过 90 秒未采样时，保留明确标为「最后读数」的历史值，不显示实时进度条。请求恢复并取得新采样后自动恢复实时显示；更换资源时更新卡片，不沿用旧 GPU 的并行判断历史。App 每 5 秒刷新，采样时间不会用连接时间代替。

后台继续通过既有申请的只读探测采样，失败按 30–300 秒退避，等待中的回执保留，提交回执不明时先核查。已确认失败或回收的资源停止采样，未就绪的申请不执行 GPU 命令。只有已完成的本服务探测规范文件会移到同一 jobs 目录中的 `.gpuq-probe-history/`，保留日志和状态，不移动运行中探测或计算任务；这避免旧探测占满平台只扫描前 100 个文件的窗口。

本次没有修改 `web/`。客户端与必要的后台采样逻辑须一并部署，更新 App 本身不会替换服务器代码。没有新增 GPU 申请或启动计算任务。

验证入口：

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/test_queue_dart.py --widgets --flutter /path/to/flutter
```

第二项通过 CPU 上的真实 Flutter 测试引擎渲染生产 App 组件，覆盖混合卡型、换卡、断线与恢复、退避提示、缺失指标、390/900 像素宽度、1.5 倍文字和深浅色。它不替代 Mac 安装及实卡长期采样验收。可选环境变量 `GPU_MONITOR_SCREENSHOT_DIR`、`GPU_MONITOR_SCREENSHOT_FONT` 用于导出原生组件示例截图。

`.github/workflows/mf39-app-monitor.yml` 对本次分支执行完整 Mac 原生检查、测试和构建，上传 QA app 与校验和，不发布正式 Release。该分支基于当前 App 更新分支 `codex/mf-33-auto-update`，不把原生 App 源码当作主分支的网页更新提交。
