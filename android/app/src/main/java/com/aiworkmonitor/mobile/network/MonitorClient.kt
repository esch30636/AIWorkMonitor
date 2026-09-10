package com.aiworkmonitor.mobile.network

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class MonitorClient(
    private val onMessage: (String) -> Unit,
    private val onState: (String) -> Unit,
) {
    private val http = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .build()
    private var socket: WebSocket? = null

    fun connect(relayUrl: String, token: String) {
        close()
        val httpRelayUrl = relayUrl.trimEnd('/')
            .replaceFirst("ws://", "http://")
            .replaceFirst("wss://", "https://")
        val url = "$httpRelayUrl/ws/mobile".toHttpUrl().newBuilder()
            .addQueryParameter("token", token)
            .build()
        val request = Request.Builder().url(url).build()
        onState("正在连接")
        socket = http.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) = onState("已连接")

            override fun onMessage(webSocket: WebSocket, text: String) = onMessage(text)

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                onState("连接关闭：$reason")
                webSocket.close(code, reason)
            }

            override fun onFailure(webSocket: WebSocket, throwable: Throwable, response: Response?) {
                onState("连接失败：${throwable.message ?: "未知错误"}")
            }
        })
    }

    fun sendClaudeCommand(deviceId: String, command: String, requestId: String): Boolean {
        val payload = JSONObject()
            .put("target", "claude-code")
            .put("command", command)
            .put("requestId", requestId)
        val message = JSONObject()
            .put("type", "command")
            .put("deviceId", deviceId)
            .put("payload", payload)
        return socket?.send(message.toString()) ?: false
    }

    fun close() {
        socket?.close(1000, "client reconnect")
        socket = null
    }
}
