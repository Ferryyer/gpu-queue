# 员工首次接入 Inspire Queue

首批客户端支持 Apple Silicon Mac、macOS 13 及以上。Windows 后续提供。每位员工使用自己的 Linux 账号、SSH 配置和飞书授权；不要复制同事的客户端数据库、私钥、飞书会话或任务库。

## 接入前准备

1. 管理员已为本人开通 Linux CPU 账号与所属平台权限。能看到飞书应用不等于已开户。
2. 本人能通过已验证服务器指纹的 SSH 登录自己的 CPU 账号。Mac 客户端使用现有个人 SSH 密钥或密码，不填写同事账号。
3. CPU 上已有 Python 3.10+、`mf-gpu`、`lark-cli`、`mf-services`。工具由管理员提供；安装器只发现现有工具，不安装管理员组件。
4. 本人按团队指南完成飞书 CLI「众解深算」组织授权。安装器不会登录、申请 GPU 或发送消息，也不能代替本人授权。不要把登录凭据放进服务 JSON。

## CPU 端首次安装

将与 Mac 发布版本配套的仓库源码放在本人 HOME 的固定目录，例如 `~/code/gpu-queue`。此目录须持续存在，安装后的服务直接从这里运行。不要使用共享目录或其他员工的 HOME；先读本人 `~/AGENTS.md` 与管理员提供的共享工具指南。

例如首次下载该版本源码（目录已存在时请先核对版本，不要覆盖）：

```sh
mkdir -p ~/code
git clone --branch v2.0.2012 --depth 1 https://github.com/Ferryyer/gpu-queue.git ~/code/gpu-queue
cd ~/code/gpu-queue
```

在该源码目录执行：

```sh
python3 scripts/install_personal_service.py
```

默认仅检查并列出即将创建的文件，不写入任何配置、任务库或日志。检查成功后首次安装：

```sh
python3 scripts/install_personal_service.py --apply
mf-services validate
mf-services status
```

它创建本人 `~/.local/bin/gpuq`、0600 的 `~/.config/gpuq/connection.json`，以及 `~/.config/markflow/services/gpuq.json` 和 `gpuq-web.json`。账号与 HOME 从实际 Linux 身份生成；配置只记录身份、平台工具路径，不含凭据。任务通过 `~/.local/bin/gpuq submit --manifest <本人任务文件> --source Codex` 提交；Claude 使用 `--source Claude`。如果本人 PATH 尚未包含 `~/.local/bin`，先使用该绝对路径。

**两项服务初始均为 `enabled: false`。** 安装不会启动或恢复调度。确认这是首次使用，或先核对已有任务库中已授权任务后，由本人将两个服务 JSON 的 `enabled` 改为 `true`，再次运行 `mf-services validate` 和 `mf-services status`。监管器按团队机制启动前台常驻服务；不要另开第二个调度器。启用已有账号的调度器可能恢复此前已经授权的队列，并按该授权申请 GPU。

已有完全相同的文件会保持不变。遇到不同配置（包括已启用服务）、符号链接或不安全权限时，安装器拒绝覆盖；这不是升级工具，请维护者检查现有版本和迁移安排。不要删除任务数据库来绕过提示。只需暂停任务台时将这两项服务设为禁用；停调度服务不等于停止 GPU 上已经投放的计算，也不等于释放 GPU。

## Mac 客户端接入

从项目正式 Release 下载匹配的 Mac DMG 并核对发布校验和，退出旧客户端后复制应用。应用内更新要求安装目录本人可写，可使用 `~/Applications`。当前 ad-hoc 签名版本未做 Apple 公证；若 macOS 阻止打开，按公司软件政策核验来源后在系统设置的「隐私与安全性」处理，受管设备由 IT 协助。

在「服务器」添加或导入本人的 CPU SSH 配置，完成主机指纹核对。在「任务」选择运行本人任务服务的 CPU 服务器并连接。客户端经已有 SSH 访问 `/tmp/gpuq-<本人UID>/web.sock`，不需要网页密码、公网端口或额外本地转发。新账号任务列表为空是正常状态；准备任务并提交后，由本人点击「开始」授权执行。

任务结果首次打开前，显式关联能访问结果路径的个人服务器。产物位于共享 HOME 时可选择个人 CPU；这个关联决定文件与终端访问目标，不代表 GPU 实际所在主机。GPU 是否在线仍以任务内的实例采样和平台回执为准。

不要安装 README 历史章节中的旧 Widget、旧 launcher 或个人隧道恢复脚本；这些兼容附件面向原个人环境。员工分发使用本节的统一原生客户端。

## 排查接入问题

- SSH 失败：先核对本人账号、密钥、服务器地址与主机指纹，再连接任务服务。
- SSH 成功而任务服务不可用：运行 `mf-services validate`、`mf-services status`，核对两项服务是否已启用及最近错误。私有 socket 的 UID 必须对应本人；不要复制别人 socket 路径。
- 能看到任务但队列不推进：分别核对 `gpuq-web` 与 `gpuq` 服务状态；网页通道成功不代表调度器在运行。查看本人 `~/.local/state/markflow-services/` 下相应日志，避免把完整日志或凭据发到公共群。
- 飞书未授权或组织权限不足：本人按团队指南授权「众解深算」组织；App 安装不会自动完成飞书授权。
- 本人已有旧服务：保留现有配置与任务库，由维护者核对源码版本后升级；更新 Mac App 不会自动更新 CPU 服务。

首次验收无需申请 GPU：确认首次启动、自己的 SSH 连接、空任务页或本人现有任务只读列表、服务状态与重新连接。新增和启动真实计算任务是验收之后由本人明确进行的操作。GPU 任务完成、停止或连接超时都不代表实例已经释放；当前平台不提供成员主动释放接口时，以平台实际回收状态为准。
