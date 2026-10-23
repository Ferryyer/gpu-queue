# GPU Queue

个人 GPU 任务台：网页、CPU 调度服务，以及 macOS 桌面小组件。

这是为 linlishuo 的 Markflow 环境编写的个人工具，包含用户身份、SSH 入口和平台适配，并非开箱即用的多用户产品。

## 组成

- `gpuqueue/`：任务固定版本、启动授权、队列控制、平台资源适配及本地网页服务。
- `web/`：任务台前端，支持 Edit / Auto 和 Shift+Tab。
- `launchers/macos/widget/`：桌面小组件及独立更新器，当前版本 1.1.2。
- `scripts/`：安装包生成工具。
- `tests/`：CPU 单元测试、安装回滚测试及浏览器验证脚本。
- `downloads/`、`updates/`：1.1.2 安装包、校验和及兼容现有更新器的更新信息。
- `worker/`、`drizzle/`、`.openai/`：旧 Sites 发布实现及配置记录；现用服务通过个人 SSH 通道访问。

[下载 macOS 桌面小组件 1.1.2](https://raw.githubusercontent.com/Ferryyer/gpu-queue/main/downloads/GPU-Queue-Widget-1.1.2-macOS.zip) · [校验和](downloads/SHA256SUMS)

## 安装桌面小组件

完整解压 `downloads/GPU-Queue-Widget-1.1.2-macOS.zip`，双击“安装桌面小组件.command”。如果旧更新器报“安装包文件路径无效”，先退出旧面板和更新窗口，再覆盖安装一次。

仅支持 macOS；原生 AppKit 运行效果仍需 Mac 实机验证。安装保留 SSH 配置等偏好。启动 GPU 任务仍需用户在网页点击“开始”。

## 本地验证

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/*.cjs tests/cloud.test.js
```

浏览器验证另需 Playwright 及其浏览器。单元测试不申请真实 GPU。

## 打包

```sh
python3 scripts/package-widget.py --output-dir ./build/widget
```

详细部署、平台限制及发布约定见 [运行说明](docs/OPERATIONS.md)。安装包校验值见 `downloads/SHA256SUMS`。

## 更新入口迁移

现有安装版本仍从 `Ferryyer/Ferryyer` 获取更新。本项目暂保留该地址，主页仓库同时保留原安装包和更新信息，确保旧客户端仍能检查更新。后续发布可将新版本迁往独立仓库，同时在主页仓库继续维护旧客户端更新信息。

本源码包不包含本地任务数据库、连接凭据、运行日志、未跟踪备份或 Git 历史。
