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
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiworkmonitor.mobile.model.DeviceSnapshot
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
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(model.connectionState, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Button(onClick = model::connect) { Text("连接") }
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
                "${it.name} ${if (it.running) "运行中" else "未运行"}"
            }.ifBlank { "等待应用状态" }
            Text(providerText, style = MaterialTheme.typography.bodyMedium)

            if (device.activity.isNotEmpty()) {
                Text("最近活动", fontWeight = FontWeight.SemiBold)
                device.activity.takeLast(4).forEach { event ->
                    Text(
                        "${event.provider}${event.role?.let { " · $it" } ?: ""}: ${event.text}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 3,
                    )
                }
            }

            if (device.claudeCommands) {
                OutlinedTextField(
                    value = command,
                    onValueChange = { command = it },
                    label = { Text("发送给 Claude Code") },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 2,
                )
                Button(
                    onClick = {
                        model.sendCommand(device.deviceId, command)
                        command = ""
                    },
                    enabled = command.isNotBlank() && device.online,
                    modifier = Modifier.align(Alignment.End),
                ) { Text("发送指令") }
                model.commandStatus?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                device.lastCommandResult?.let {
                    Text("最近结果", fontWeight = FontWeight.SemiBold)
                    Text(it, style = MaterialTheme.typography.bodySmall, maxLines = 8)
                }
            } else {
                Text("此设备未启用 Claude 远程指令", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

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
