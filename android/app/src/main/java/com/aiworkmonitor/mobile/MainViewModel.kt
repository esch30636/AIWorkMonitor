package com.aiworkmonitor.mobile

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiworkmonitor.mobile.model.DeviceSnapshot
import com.aiworkmonitor.mobile.model.parseSnapshot
import com.aiworkmonitor.mobile.network.MonitorClient
import kotlinx.coroutines.launch
import java.util.UUID

class MainViewModel : ViewModel() {
    var relayUrl by mutableStateOf("ws://10.0.2.2:8765")
    var token by mutableStateOf("")
    var connectionState by mutableStateOf("未连接")
        private set
    var devices by mutableStateOf<List<DeviceSnapshot>>(emptyList())
        private set
    var commandStatus by mutableStateOf<String?>(null)
        private set

    private val client = MonitorClient(
        onMessage = { message ->
            viewModelScope.launch {
                runCatching { parseSnapshot(message) }
                    .onSuccess { parsed -> if (parsed.isNotEmpty() || message.contains("\"devices\":[]")) devices = parsed }
                    .onFailure { connectionState = "数据解析失败：${it.message}" }
            }
        },
        onState = { state -> viewModelScope.launch { connectionState = state } },
    )

    fun connect() {
        if (relayUrl.isBlank() || token.isBlank()) {
            connectionState = "请填写中继地址和令牌"
            return
        }
        runCatching { client.connect(relayUrl, token) }
            .onFailure { connectionState = "地址无效：${it.message}" }
    }

    fun sendCommand(deviceId: String, command: String) {
        if (command.isBlank()) return
        val sent = client.sendClaudeCommand(deviceId, command.trim(), UUID.randomUUID().toString())
        commandStatus = if (sent) "指令已发送" else "发送失败：当前未连接"
    }

    override fun onCleared() {
        client.close()
        super.onCleared()
    }
}

