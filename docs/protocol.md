# WebSocket protocol v0.2

所有消息都是 UTF-8 JSON，使用统一 envelope：

```json
{
  "type": "telemetry",
  "deviceId": "windows-main",
  "timestamp": "2026-09-10T08:00:00Z",
  "payload": {}
}
```

## 连接

- 电脑代理：`/ws/agent/{deviceId}?token=...`
- Android：`/ws/mobile?token=...`
- REST 快照：`GET /api/devices`，请求头 `Authorization: Bearer ...`

当前令牌是部署级共享密钥，只适合开发或可信局域网。公网部署必须在反向代理启用 TLS，并在下一阶段替换为设备配对和短期凭据。

## 代理上行消息

- `hello`：设备名称、OS、架构和 capability。
- `telemetry`：CPU、内存、GPU/显存指标。
- `provider_state`：Claude Code、ChatGPT 是否运行及进程摘要。Claude Code 的 `activeSessions` 使用本机运行时登记表精确列出每个进程当前绑定的会话；`activeSession` 保留为首个活跃会话以兼容旧客户端；`sessions` 提供最多 50 个会话，并附带项目根目录、当前工作目录、进程 PID、状态、标题、最近提示、分支、模型和最后活动时间。
- `activity`：适配器发现的新增活动；Claude Code 活动会附带对应的项目名、项目路径和 session ID。
- `command_result`：Claude 指令最终结果。

## 手机下行消息

```json
{
  "type": "command",
  "deviceId": "ubuntu-worker",
  "payload": {
    "target": "claude-code",
    "action": "prompt",
    "command": "运行测试并解释失败原因",
    "requestId": "android-generated-uuid",
    "sessionId": "12345678-1234-1234-1234-123456789abc",
    "model": "sonnet",
    "effort": "high"
  }
}
```

字段说明：

- `action`：`prompt` 发送普通指令；`compact` 在所选会话中执行 `/compact`，此时 `command` 是可选的压缩重点说明。
- `sessionId`：从 `provider_state.sessions` 选择；活跃会话来自 Claude Code 的 PID 会话登记，而不是根据全局最新日志猜测。省略时回退到首个活跃会话。
- `model`：`session` 保持恢复会话原有模型；也可选择 Claude Code 内置别名，或传入最长 256 字符且不含控制字符的企业网关/第三方提供商模型 ID。
- `effort`：`auto`、`low`、`medium`、`high`、`xhigh`、`max` 或 `ultracode`。

中继只把 `target=claude-code` 的合法消息转发给在线目标设备。电脑代理会再次检查 `AIWM_ALLOW_CLAUDE_COMMANDS`，确认所选 session 确实存在于本机，再从该会话所属的 Claude 项目根目录通过 Claude CLI 恢复会话。日志事件里的临时子目录不会被误用为恢复目录。所有参数均以独立进程参数传递，不经过 shell。
