# AIWorkMonitor

一个面向局域网/自托管场景的 AI 编程工作台监控框架。Android 手机通过中继服务查看 Windows、Ubuntu 电脑上的 Claude Code / ChatGPT 桌面应用状态及硬件遥测，并可向 Claude Code 发送指令。

## 当前骨架包含

- `relay/`：FastAPI WebSocket 中继，管理电脑代理、手机连接、最新状态和指令转发。
- `agent/`：Windows/Ubuntu Python 代理，采集 CPU、内存、NVIDIA GPU、显存、温度和功耗，并提供 Claude Code / ChatGPT 状态适配器。
- `android/`：Jetpack Compose 客户端，支持连接配置、设备列表、实时指标、活动流，以及 Claude Code 会话、模型、思考强度、指令和 `/compact` 控制。
- `docs/protocol.md`：手机、中继、电脑代理之间的消息协议。

## 数据流

```text
Windows / Ubuntu                 自托管中继                    Android
┌──────────────────┐       ┌────────────────────┐       ┌──────────────────┐
│ agent            │  WSS  │ relay              │  WSS  │ Compose app      │
│ - system metrics ├───────►│ - auth             ├──────►│ - live dashboard │
│ - Claude adapter │◄───────┤ - latest snapshot  │◄──────┤ - Claude input   │
│ - ChatGPT adapter│       │ - command routing  │       │                  │
└──────────────────┘       └────────────────────┘       └──────────────────┘
```

## 快速启动

要求 Python 3.11+。在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
$env:AIWM_TOKEN = "请替换为足够长的随机令牌"
aiwm-relay
```

另开终端启动本机代理：

```powershell
.\.venv\Scripts\Activate.ps1
$env:AIWM_TOKEN = "与中继相同的令牌"
$env:AIWM_RELAY_URL = "ws://127.0.0.1:8765"
$env:AIWM_DEVICE_NAME = "windows-main"
aiwm-agent
```

Ubuntu 使用相同环境变量与命令。Android Studio 打开 `android/`，运行后填写中继地址（真机局域网示例：`ws://192.168.1.20:8765`）和令牌。

### 跨网络连接（Tailscale）

让中继电脑、各采集电脑和手机登录同一个 Tailnet。中继绑定其 Tailscale IP，其他设备使用 MagicDNS 名称连接，例如：

```text
ws://lenovo-83bf.tailaed876.ts.net:8765
```

该方式不需要公网 IP 或路由器端口映射。详细部署方式见 `docs/tailscale.md`。

## Windows EXE

执行以下命令生成单文件 Windows 代理：

```powershell
.\scripts\build-windows.ps1
```

产物位于 `dist/AIWorkMonitorAgent.exe`。首次运行会为这台电脑生成永久访问令牌；安装后 EXE 会同时托管本机中继和 Agent，并自动设置当前 Windows 用户开机后台运行。关闭图形界面不会停止监控。

再次打开应用时，首页只显示 Android 端需要填写的三项内容：自动读取的电脑名称、优先使用 Tailscale IP 的 WebSocket 地址和永久访问令牌。令牌不可在界面中修改，更新安装时也会沿用目标电脑已有的令牌。

控制台的“安装与开机启动”区域支持：

- 浏览并选择任意可写安装目录；
- 将当前单文件 EXE 和配置复制到所选目录；
- 强制使用当前 Windows 账户开机静默启动，无需管理员权限；
- 后台进程同时运行中继和本机 Agent，异常后自动重试；
- 高级设置默认收起，仅保留安装目录和采样间隔等低频选项。

访问令牌优先使用 Windows DPAPI 加密后写入 `aiworkmonitor.env`，只能由保存令牌的 Windows 账户解密。开机启动使用 `--background` 参数，日志写入安装目录的 `logs/agent.log`。

仍可使用以下命令在不连接中继的情况下检查配置和硬件采集：

```powershell
.\dist\AIWorkMonitorAgent.exe --check
```

需要手动静默运行时：

```powershell
.\dist\AIWorkMonitorAgent.exe --background
```

Agent 会联合读取 `~/.claude/sessions/*.json`、`~/.claude/history.jsonl` 与 `~/.claude/projects/**/*.jsonl`：运行时登记表用于把每个 Claude 进程精确绑定到当前 session ID，历史记录用于取得项目根目录和最近提示，项目日志用于活动流和模型信息。因此不需要在电脑端配置工作目录，并且多个项目同时运行、终端内执行过 `/resume`、会话进入子目录等情况不会再依赖“全局最新日志”猜测。Windows 首次配置默认允许手机向 Claude Code 下发指令，也可在高级设置中关闭；Ubuntu 代理需要显式设置：

```powershell
$env:AIWM_ALLOW_CLAUDE_COMMANDS = "true"
aiwm-agent
```

手机端会把所有正在运行的 Claude Code 会话置顶，并列出最近 50 个本机会话。每项显示项目根目录名、对话标题或最近提示、session ID 前缀和运行状态；详情区另外显示当前工作子目录。用户选择会话后，普通指令和 `/compact` 都会通过 `claude -p --resume <session-id>` 从正确的项目根目录作用于该会话，并可保持会话当前模型、选择 Claude Code 模型别名或输入企业网关自定义模型 ID，同时支持 `low` 至 `max` 和 `ultracode` 思考强度。Fable 和部分 1M 上下文选项可能使用额外额度，具体取决于 Anthropic 账户。调用不会经过 shell。请仅通过 Tailscale 或其他受控网络使用该功能。

## 硬件数据说明

- CPU 占用、内存：使用 `psutil`，Windows/Ubuntu 均可用。
- NVIDIA GPU 温度、功耗、占用、显存：使用 `nvidia-smi`。
- Windows Intel/AMD GPU 占用和显存：使用系统 PDH 性能计数器作为回退采集器。
- Ubuntu CPU 温度：使用内核 hwmon/`psutil`；CPU 功耗：读取 RAPL。
- Windows CPU/GPU 温度和 CPU 功耗：若安装并运行 LibreHardwareMonitor，代理会读取其 WMI 数据；否则对应字段为 `null`，其余指标仍正常工作。
- AMD/Intel 独显采集器保留为后续插件扩展点。

## ChatGPT 与 Claude Code 的边界

Claude Code 适配器会跟随每个运行进程登记的会话 JSONL，把准确的会话列表、项目根目录、当前工作目录、状态和新增活动推送到手机，并通过独立的 `claude -p --resume` 调用执行手机指令、模型/思考强度选择和上下文压缩。ChatGPT 桌面应用目前没有稳定公开的“实时任务流”接口，因此骨架默认提供进程在线状态与可配置日志文件尾读；更深层集成放在 `ActivityProvider` 适配器边界内，不依赖 UI 抓取。

## 下一阶段建议

1. 为中继加入设备注册、短期令牌和 TLS/WSS。
2. 在手机端展示 Claude 指令的流式 token，并显示每个会话的上下文用量。
3. 增加 AMD ROCm/ADLX 与 Intel oneAPI/PresentMon 采集器。
4. 为 ChatGPT/Codex 接入稳定的本地事件源或官方接口。
5. 增加 Android 后台通知、历史曲线和设备配对二维码。
