package com.aiworkmonitor.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiworkmonitor.mobile.model.DeviceSnapshot
import com.aiworkmonitor.mobile.model.ClaudeSessionState
import com.aiworkmonitor.mobile.model.GpuMetric
import com.aiworkmonitor.mobile.storage.SavedConnection
import kotlinx.coroutines.launch
import java.util.Locale

private val AppColors = darkColorScheme(
    primary = Color(0xFF70D7A7),
    secondary = Color(0xFF77B7FF),
    background = Color(0xFF10131A),
    surface = Color(0xFF191E28),
)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = AppColors) {
                Surface(modifier = Modifier.fillMaxSize()) {
                    MonitorScreen()
                }
            }
        }
    }
}

@Composable
private fun MonitorScreen(model: MainViewModel = viewModel()) {
    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
    val scope = rememberCoroutineScope()

    ModalNavigationDrawer(
        drawerState = drawerState,
        gesturesEnabled = true,
        drawerContent = {
            SavedConnectionsDrawer(
                connections = model.savedConnections,
                activeConnectionId = model.activeConnectionId,
                onConnectionSelected = { connection ->
                    model.connectSaved(connection)
                    scope.launch { drawerState.close() }
                },
                onClose = { scope.launch { drawerState.close() } },
            )
        },
    ) {
        Column(Modifier.fillMaxSize().safeDrawingPadding()) {
            AppHeader(onOpenDrawer = { scope.launch { drawerState.open() } })
            LazyColumn(
                modifier = Modifier.fillMaxWidth().weight(1f).padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                item { ConnectionCard(model) }
                if (model.devices.isEmpty()) {
                    item {
                        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                            Text("尚无设备。启动电脑代理后会自动出现在这里。", modifier = Modifier.padding(20.dp))
                        }
                    }
                } else {
                    items(model.devices, key = { it.deviceId }) { device -> DeviceCard(device, model) }
                }
                item { Spacer(Modifier.height(24.dp)) }
            }
        }
    }
}

@Composable
private fun AppHeader(onOpenDrawer: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onOpenDrawer) {
            Text("☰", fontSize = 26.sp)
        }
        Column {
            Text("AI Work Monitor", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text("电脑工作状态与硬件遥测", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun SavedConnectionsDrawer(
    connections: List<SavedConnection>,
    activeConnectionId: String?,
    onConnectionSelected: (SavedConnection) -> Unit,
    onClose: () -> Unit,
) {
    ModalDrawerSheet {
        Row(
            modifier = Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 12.dp, bottom = 8.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text("已保存的连接", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Text("点击设备即可自动连接", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = onClose) { Text("×", fontSize = 28.sp) }
        }
        HorizontalDivider()
        if (connections.isEmpty()) {
            Box(Modifier.fillMaxWidth().padding(24.dp)) {
                Text("暂无历史连接。首次连接成功后会自动保存。", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        } else {
            LazyColumn(Modifier.fillMaxSize().padding(horizontal = 12.dp, vertical = 8.dp)) {
                items(connections, key = { it.id }) { connection ->
                    NavigationDrawerItem(
                        label = {
                            Column(Modifier.padding(vertical = 4.dp)) {
                                Text(connection.name, fontWeight = FontWeight.SemiBold)
                                Text(connection.relayUrl, style = MaterialTheme.typography.bodySmall, maxLines = 1)
                                Text("令牌已加密保存", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        },
                        selected = connection.id == activeConnectionId,
                        onClick = { onConnectionSelected(connection) },
                        modifier = Modifier.padding(vertical = 3.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun ConnectionCard(model: MainViewModel) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(
                value = model.connectionName,
                onValueChange = { model.connectionName = it },
                label = { Text("设备名称（可选）") },
                supportingText = { Text("留空时使用地址中的主机名") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = model.relayUrl,
                onValueChange = { model.relayUrl = it },
                label = { Text("中继 WebSocket 地址") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = model.token,
                onValueChange = { model.token = it },
                label = { Text("访问令牌") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = model::connect,
                modifier = Modifier.fillMaxWidth(),
            ) { Text(model.connectionActionLabel()) }
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = Color(0xFF232A36),
                shape = RoundedCornerShape(10.dp),
            ) {
                Text(
                    model.connectionState,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                "连接成功后，名称、地址和令牌会保存在本机；令牌使用 Android Keystore 加密。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun DeviceCard(device: DeviceSnapshot, model: MainViewModel) {
    var command by remember(device.deviceId) { mutableStateOf("") }
    var compactInstructions by remember(device.deviceId) { mutableStateOf("") }
    var selectedModel by remember(device.deviceId) { mutableStateOf("session") }
    var customModel by remember(device.deviceId) { mutableStateOf("") }
    var selectedEffort by remember(device.deviceId) { mutableStateOf("auto") }
    var selectedSessionId by remember(device.deviceId) { mutableStateOf("") }
    val claudeProvider = device.providers.firstOrNull { it.name == "claude-code" }
    val activeSessions = claudeProvider?.activeSessions.orEmpty().ifEmpty {
        listOfNotNull(claudeProvider?.activeSession?.takeIf { it.active })
    }
    val activeClaude = activeSessions.firstOrNull() ?: claudeProvider?.activeSession
    val sessions = claudeProvider?.sessions.orEmpty().ifEmpty { listOfNotNull(activeClaude) }

    LaunchedEffect(sessions.map { it.sessionId }, activeClaude?.sessionId) {
        if (sessions.none { it.sessionId == selectedSessionId }) {
            selectedSessionId = activeClaude?.sessionId ?: sessions.firstOrNull()?.sessionId.orEmpty()
        }
    }
    val selectedSession = sessions.firstOrNull { it.sessionId == selectedSessionId } ?: activeClaude
    val knownModels = setOf("default", "best", "fable", "sonnet", "opus", "haiku", "sonnet[1m]", "opus[1m]", "opusplan")
    val currentCustomModel = selectedSession?.model?.takeIf { it.isNotBlank() && it !in knownModels }
    val modelOptions = buildList {
        add("session" to "保持所选会话模型")
        currentCustomModel?.let { add(it to "当前会话：$it") }
        add("default" to "跟随 Claude 默认")
        add("best" to "Best（自动选择最强可用模型）")
        add("fable" to "Fable（可能使用额外额度）")
        add("sonnet" to "Sonnet")
        add("opus" to "Opus")
        add("haiku" to "Haiku")
        add("sonnet[1m]" to "Sonnet · 1M 上下文")
        add("opus[1m]" to "Opus · 1M 上下文")
        add("opusplan" to "Opus Plan / Sonnet 执行")
        add("custom" to "输入自定义模型 ID…")
    }
    val effectiveModel = if (selectedModel == "custom") customModel.trim() else selectedModel
    val modelSelectionValid = effectiveModel.isNotBlank()
    Card(
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) {
                    Text(device.name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                    Text(device.os, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2)
                }
                StatusPill(if (device.online) "在线" else "离线", device.online)
            }

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Metric("CPU", percent(device.cpu.usagePercent), "${value(device.cpu.temperatureC, "°C")} · ${value(device.cpu.powerW, "W")}", Modifier.weight(1f))
                Metric("内存", percent(device.memory.usagePercent), "${bytes(device.memory.usedBytes)} / ${bytes(device.memory.totalBytes)}", Modifier.weight(1f))
            }
            device.gpus.forEach { GpuRow(it) }

            val providerText = device.providers.joinToString(" · ") {
                val runningCount = it.activeSessions.size.takeIf { count -> count > 0 }
                val project = it.activeSession?.projectName?.takeIf { name -> name.isNotBlank() }
                "${it.name} ${if (it.running) "运行中" else "未运行"}${
                    runningCount?.let { count -> " · $count 个会话" }
                        ?: project?.let { name -> " · $name" }.orEmpty()
                }"
            }.ifBlank { "等待应用状态" }
            Text(providerText, style = MaterialTheme.typography.bodyMedium)

            val shownActiveSessions = activeSessions.ifEmpty { listOfNotNull(activeClaude) }
            if (shownActiveSessions.isNotEmpty()) {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    color = Color(0xFF232A36),
                    shape = RoundedCornerShape(10.dp),
                ) {
                    Column(Modifier.padding(12.dp)) {
                        Text(
                            if (activeSessions.isNotEmpty()) "正在监听 ${activeSessions.size} 个 Claude Code 会话" else "最近的 Claude Code 会话",
                            fontWeight = FontWeight.SemiBold,
                        )
                        shownActiveSessions.forEach { session ->
                            Text(
                                "${if (session.active) "● " else ""}${session.projectName} · ${sessionTitle(session)} · ${session.sessionId.take(8)}${session.status?.let { " · ${sessionStatus(it)}" } ?: ""}",
                                color = MaterialTheme.colorScheme.primary,
                                fontWeight = FontWeight.Medium,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                session.projectPath,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
            }

            if (device.activity.isNotEmpty()) {
                Text("最近活动", fontWeight = FontWeight.SemiBold)
                device.activity.takeLast(4).forEach { event ->
                    Text(
                        "${event.provider}${event.projectName?.let { " · $it" } ?: ""}${event.role?.let { " · $it" } ?: ""}: ${event.text}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 3,
                    )
                }
            }

            if (device.claudeCommands) {
                Text("Claude Code 控制", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(
                    "选择会话后，每条指令都会通过 /resume 恢复该会话。模型和思考强度应用于手机发起的操作。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                OptionMenu(
                    label = "/resume 会话",
                    selectedLabel = selectedSession?.let(::sessionLabel) ?: "未发现可恢复会话",
                    options = sessions.map { it.sessionId to sessionLabel(it) },
                    onSelected = { selectedSessionId = it },
                    enabled = sessions.isNotEmpty() && device.online,
                )
                selectedSession?.let { session ->
                    Text(
                        buildString {
                            append(session.projectPath)
                            session.workingDirectory
                                ?.takeIf { it.isNotBlank() && !it.equals(session.projectPath, ignoreCase = true) }
                                ?.let { append(" · 当前目录 ").append(it) }
                            session.gitBranch?.let { append(" · ").append(it) }
                            session.model?.let { append(" · 当前 ").append(it) }
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OptionMenu(
                        label = "模型",
                        selectedLabel = modelLabel(selectedModel),
                        options = modelOptions,
                        onSelected = { selectedModel = it },
                        modifier = Modifier.weight(1f),
                    )
                    OptionMenu(
                        label = "思考强度",
                        selectedLabel = effortLabel(selectedEffort),
                        options = listOf(
                            "auto" to "自动",
                            "low" to "Low",
                            "medium" to "Medium",
                            "high" to "High",
                            "xhigh" to "XHigh",
                            "max" to "Max",
                            "ultracode" to "Ultracode",
                        ),
                        onSelected = { selectedEffort = it },
                        modifier = Modifier.weight(1f),
                    )
                }
                if (selectedModel == "custom") {
                    OutlinedTextField(
                        value = customModel,
                        onValueChange = { customModel = it.take(256) },
                        label = { Text("自定义模型 ID") },
                        supportingText = { Text("适用于 DeepSeek 或企业网关等自定义模型") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                OutlinedTextField(
                    value = command,
                    onValueChange = { command = it },
                    label = { Text("发送到 ${selectedSession?.projectName ?: "所选 Claude 会话"}") },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 2,
                )
                Button(
                    onClick = {
                        model.sendCommand(
                            device.deviceId,
                            command,
                            selectedSession?.sessionId,
                            effectiveModel,
                            selectedEffort,
                        )
                        command = ""
                    },
                    enabled = command.isNotBlank() && selectedSession != null && modelSelectionValid && device.online,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("发送指令") }

                HorizontalDivider()
                Text("压缩会话上下文", fontWeight = FontWeight.SemiBold)
                OutlinedTextField(
                    value = compactInstructions,
                    onValueChange = { compactInstructions = it },
                    label = { Text("/compact 重点说明（可选）") },
                    supportingText = { Text("例如：保留测试结果和未完成事项") },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 1,
                )
                OutlinedButton(
                    onClick = {
                        model.compactSession(
                            device.deviceId,
                            compactInstructions,
                            selectedSession?.sessionId,
                            effectiveModel,
                            selectedEffort,
                        )
                    },
                    enabled = selectedSession != null && modelSelectionValid && device.online,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("执行 /compact") }
                model.commandStatus?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                device.lastCommandResult?.let {
                    Text(if (it.ok) "最近操作成功" else "最近操作失败", fontWeight = FontWeight.SemiBold)
                    Text(it.output.ifBlank { "Claude Code 未返回文字" }, style = MaterialTheme.typography.bodySmall, maxLines = 12)
                }
            } else {
                Text("此设备未启用 Claude 远程指令", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun OptionMenu(
    label: String,
    selectedLabel: String,
    options: List<Pair<String, String>>,
    onSelected: (String) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    var expanded by remember { mutableStateOf(false) }
    Box(modifier) {
        OutlinedButton(
            onClick = { expanded = true },
            enabled = enabled && options.isNotEmpty(),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(Modifier.fillMaxWidth()) {
                Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(selectedLabel, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            options.forEach { (value, title) ->
                DropdownMenuItem(
                    text = { Text(title) },
                    onClick = {
                        onSelected(value)
                        expanded = false
                    },
                )
            }
        }
    }
}

private fun sessionLabel(session: ClaudeSessionState): String {
    return "${if (session.active) "● " else ""}${session.projectName} · ${sessionTitle(session)} · ${session.sessionId.take(8)}"
}

private fun sessionTitle(session: ClaudeSessionState): String =
    session.displayName?.takeIf { it.isNotBlank() }
        ?: session.lastPrompt?.lineSequence()?.firstOrNull()?.trim()?.take(60)?.takeIf { it.isNotBlank() }
        ?: "未命名会话"

private fun sessionStatus(status: String): String = when (status.lowercase()) {
    "busy", "working" -> "工作中"
    "idle" -> "等待输入"
    else -> status
}

private fun modelLabel(model: String): String = when (model) {
    "session" -> "保持会话模型"
    "default" -> "Claude 默认"
    "best" -> "Best"
    "fable" -> "Fable"
    "sonnet" -> "Sonnet"
    "opus" -> "Opus"
    "haiku" -> "Haiku"
    "sonnet[1m]" -> "Sonnet · 1M"
    "opus[1m]" -> "Opus · 1M"
    "opusplan" -> "Opus Plan"
    "custom" -> "自定义模型"
    else -> model
}

private fun effortLabel(effort: String): String = if (effort == "auto") "自动" else effort.replaceFirstChar { it.uppercase() }

@Composable
private fun GpuRow(gpu: GpuMetric) {
    Column {
        Text(gpu.name, fontWeight = FontWeight.SemiBold)
        Text(
            "占用 ${percent(gpu.usagePercent)} · ${value(gpu.temperatureC, "°C")} · ${value(gpu.powerW, "W")} · 显存 ${bytes(gpu.memoryUsedBytes)} / ${bytes(gpu.memoryTotalBytes)}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun Metric(label: String, primary: String, secondary: String, modifier: Modifier = Modifier) {
    Card(modifier = modifier, colors = CardDefaults.cardColors(containerColor = Color(0xFF232A36))) {
        Column(Modifier.padding(12.dp)) {
            Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(primary, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(secondary, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun StatusPill(text: String, online: Boolean) {
    Surface(color = if (online) Color(0xFF174C38) else Color(0xFF4B2930), shape = RoundedCornerShape(50)) {
        Text(text, modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp), style = MaterialTheme.typography.labelMedium)
    }
}

private fun percent(value: Double?): String = value?.let { String.format(Locale.US, "%.0f%%", it) } ?: "--"
private fun value(value: Double?, suffix: String): String = value?.let { String.format(Locale.US, "%.1f%s", it, suffix) } ?: "--"
private fun bytes(value: Long): String {
    if (value <= 0) return "--"
    val gib = value.toDouble() / 1024 / 1024 / 1024
    return String.format(Locale.US, "%.1f GB", gib)
}
