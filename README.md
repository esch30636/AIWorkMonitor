# AIWorkMonitor

一个面向局域网/自托管场景的 AI 编程工作台监控框架。Android 手机通过中继服务查看 Windows、Ubuntu 电脑上的 Claude Code / ChatGPT 桌面应用状态及硬件遥测，并可向 Claude Code 发送指令。

## 当前骨架包含

- `relay/`：FastAPI WebSocket 中继，管理电脑代理、手机连接、最新状态和指令转发。
- `agent/`：Windows/Ubuntu Python 代理，采集 CPU、内存、NVIDIA GPU、显存、温度和功耗，并提供 Claude Code / ChatGPT 状态适配器。
- `android/`：Jetpack Compose 客户端，支持连接配置、设备列表、实时指标、活动流与 Claude Code 指令输入。
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

产物位于 `dist/AIWorkMonitorAgent.exe`。双击后打开 Windows 图形化控制台，可填写中继地址、访问令牌、设备名和 Claude 工作目录，并可直接启动/停止 Agent、查看连接日志和检测本机硬件。

控制台的“安装与开机启动”区域支持：

- 浏览并选择任意可写安装目录；
- 将当前单文件 EXE 和配置复制到所选目录；
- 使用当前 Windows 账户设置开机静默启动，无需管理员权限；
- 后续重新选择目录或关闭开机启动。

访问令牌优先使用 Windows DPAPI 加密后写入 `aiworkmonitor.env`，只能由保存令牌的 Windows 账户解密。开机启动使用 `--background` 参数，日志写入安装目录的 `logs/agent.log`。

仍可使用以下命令在不连接中继的情况下检查配置和硬件采集：

```powershell
.\dist\AIWorkMonitorAgent.exe --check
```

需要手动静默运行时：

```powershell
.\dist\AIWorkMonitorAgent.exe --background
```

若要启用手机向 Claude Code 下发指令，需要在电脑代理上显式设置：

```powershell
$env:AIWM_ALLOW_CLAUDE_COMMANDS = "true"
$env:AIWM_CLAUDE_WORKDIR = "D:\\your-project"
aiwm-agent
```

代理会以参数数组直接启动 `claude -p`，不会经过 shell。默认禁用远程指令，避免误把未加固的开发中继暴露后直接获得代码执行入口。

## 硬件数据说明

- CPU 占用、内存：使用 `psutil`，Windows/Ubuntu 均可用。
- NVIDIA GPU 温度、功耗、占用、显存：使用 `nvidia-smi`。
- Windows Intel/AMD GPU 占用和显存：使用系统 PDH 性能计数器作为回退采集器。
- Ubuntu CPU 温度：使用内核 hwmon/`psutil`；CPU 功耗：读取 RAPL。
- Windows CPU/GPU 温度和 CPU 功耗：若安装并运行 LibreHardwareMonitor，代理会读取其 WMI 数据；否则对应字段为 `null`，其余指标仍正常工作。
- AMD/Intel 独显采集器保留为后续插件扩展点。

## ChatGPT 与 Claude Code 的边界

Claude Code 适配器可读取本机 Claude 会话 JSONL 的新增活动，并通过独立的 `claude -p` 调用执行手机指令。ChatGPT 桌面应用目前没有稳定公开的“实时任务流”接口，因此骨架默认提供进程在线状态与可配置日志文件尾读；更深层集成放在 `ActivityProvider` 适配器边界内，不依赖 UI 抓取。

## 下一阶段建议

1. 为中继加入设备注册、短期令牌和 TLS/WSS。
2. 将 Claude 命令通道升级为可恢复 session，并在手机端展示流式 token。
3. 增加 AMD ROCm/ADLX 与 Intel oneAPI/PresentMon 采集器。
4. 为 ChatGPT/Codex 接入稳定的本地事件源或官方接口。
5. 增加 Android 后台通知、历史曲线和设备配对二维码。
