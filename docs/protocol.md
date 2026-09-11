# WebSocket protocol v0.1

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
- `provider_state`：Claude Code、ChatGPT 是否运行及进程摘要。Claude Code 的 `activeSession` 包含自动发现的 `sessionId`、`projectName`、`projectPath`、`lastActivityAt` 和 `active`。
- `activity`：适配器发现的新增活动；Claude Code 活动会附带对应的项目名、项目路径和 session ID。
- `command_result`：Claude 指令最终结果。

## 手机下行消息

```json
{
  "type": "command",
  "deviceId": "ubuntu-worker",
  "payload": {
    "target": "claude-code",
    "command": "运行测试并解释失败原因",
    "requestId": "android-generated-uuid"
  }
}
```

中继只把 `target=claude-code` 的合法消息转发给在线目标设备。电脑代理还会独立检查 `AIWM_ALLOW_CLAUDE_COMMANDS`，并自动在最近活跃项目目录中恢复对应的 Claude session；手机和电脑端都不需要填写工作路径。
