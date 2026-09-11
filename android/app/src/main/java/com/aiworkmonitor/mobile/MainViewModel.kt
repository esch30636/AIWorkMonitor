package com.aiworkmonitor.mobile

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.aiworkmonitor.mobile.model.DeviceSnapshot
import com.aiworkmonitor.mobile.model.parseSnapshot
import com.aiworkmonitor.mobile.network.MonitorClient
import com.aiworkmonitor.mobile.storage.ConnectionStore
import com.aiworkmonitor.mobile.storage.SavedConnection
import kotlinx.coroutines.launch
import java.net.URI
import java.util.UUID

class MainViewModel(application: Application) : AndroidViewModel(application) {
    var connectionName by mutableStateOf("")
    var relayUrl by mutableStateOf("ws://10.0.2.2:8765")
    var token by mutableStateOf("")
    var connectionState by mutableStateOf("未连接")
        private set
    var devices by mutableStateOf<List<DeviceSnapshot>>(emptyList())
        private set
    var commandStatus by mutableStateOf<String?>(null)
        private set
    var savedConnections by mutableStateOf<List<SavedConnection>>(emptyList())
        private set
    var activeConnectionId by mutableStateOf<String?>(null)
        private set
    var hasAttemptedConnection by mutableStateOf(false)
        private set

    private val connectionStore = ConnectionStore(application)
    private var pendingConnection: PendingConnection? = null

    init {
        savedConnections = connectionStore.load()
    }

    private val client = MonitorClient(
        onMessage = { message ->
            viewModelScope.launch {
                runCatching { parseSnapshot(message) }
                    .onSuccess { parsed -> if (parsed.isNotEmpty() || message.contains("\"devices\":[]")) devices = parsed }
                    .onFailure { connectionState = "数据解析失败：${it.message}" }
            }
        },
        onState = { state ->
            viewModelScope.launch {
                connectionState = state
                if (state == "已连接") {
                    pendingConnection?.let { pending ->
                        runCatching {
                            connectionStore.save(pending.name, pending.relayUrl, pending.token)
                        }.onSuccess { saved ->
                            savedConnections = connectionStore.load()
                            activeConnectionId = saved.id
                        }.onFailure {
                            connectionState = "已连接，但保存连接失败：${it.message}"
                        }
                    }
                }
            }
        },
    )

    fun connect() {
        hasAttemptedConnection = true
        if (relayUrl.isBlank() || token.isBlank()) {
            connectionState = "请填写中继地址和令牌"
            return
        }
        val resolvedName = connectionName.trim().ifBlank { defaultConnectionName(relayUrl) }
        connectionName = resolvedName
        pendingConnection = PendingConnection(resolvedName, relayUrl.trim(), token)
        activeConnectionId = null
        runCatching { client.connect(relayUrl, token) }
            .onFailure { connectionState = "地址无效：${it.message}" }
    }

    fun connectionActionLabel(): String = if (hasAttemptedConnection) "重新连接" else "连接"

    fun connectSaved(connection: SavedConnection) {
        connectionName = connection.name
        relayUrl = connection.relayUrl
        token = connection.token
        connect()
    }

    fun sendCommand(
        deviceId: String,
        command: String,
        sessionId: String?,
        model: String,
        effort: String,
    ) {
        if (command.isBlank()) return
        val sent = client.sendClaudeCommand(
            deviceId = deviceId,
            action = "prompt",
            command = command.trim(),
            requestId = UUID.randomUUID().toString(),
            sessionId = sessionId,
            model = model,
            effort = effort,
        )
        commandStatus = if (sent) "指令已发送到所选会话" else "发送失败：当前未连接"
    }

    fun compactSession(
        deviceId: String,
        instructions: String,
        sessionId: String?,
        model: String,
        effort: String,
    ) {
        val sent = client.sendClaudeCommand(
            deviceId = deviceId,
            action = "compact",
            command = instructions.trim(),
            requestId = UUID.randomUUID().toString(),
            sessionId = sessionId,
            model = model,
            effort = effort,
        )
        commandStatus = if (sent) "已发送 /compact" else "发送失败：当前未连接"
    }

    override fun onCleared() {
        client.close()
        super.onCleared()
    }

    private fun defaultConnectionName(url: String): String = runCatching {
        val httpUrl = url.trim().replaceFirst("ws://", "http://").replaceFirst("wss://", "https://")
        URI(httpUrl).host?.takeIf { it.isNotBlank() }
    }.getOrNull() ?: "我的电脑"

    private data class PendingConnection(
        val name: String,
        val relayUrl: String,
        val token: String,
    )
}
