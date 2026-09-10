# Tailscale 跨网络部署

选择一台保持在线的 Windows 或 Ubuntu 电脑作为中继节点。所有电脑代理和 Android 手机需要登录同一个 Tailnet。

## 中继节点

将中继只绑定到它的 Tailscale IPv4 地址：

```powershell
$env:AIWM_TOKEN = "使用足够长的随机令牌"
$env:AIWM_HOST = "100.x.y.z"
$env:AIWM_PORT = "8765"
aiwm-relay
```

## Windows/Ubuntu 代理

代理可以使用中继的稳定 MagicDNS 名称：

```text
AIWM_RELAY_URL=ws://relay-host.your-tailnet.ts.net:8765
```

每台代理使用相同部署令牌，并设置不同的 `AIWM_DEVICE_NAME`。不要在 Git 中提交真实令牌。

## Android

1. 安装 Tailscale Android 应用并登录同一 Tailnet。
2. 在 AI Work Monitor 中填写中继的 MagicDNS WebSocket 地址。
3. 填写与中继相同的访问令牌并连接。
4. 关闭 Wi-Fi、改用移动数据，可验证跨网络连接。

Tailscale 本身会加密节点间流量，所以开发版可以在 Tailnet 内使用 `ws://`。若未来允许非 Tailnet 客户端访问，应改用 TLS/WSS、设备配对和短期令牌。
