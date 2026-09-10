package com.aiworkmonitor.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiworkmonitor.mobile.model.DeviceSnapshot
import com.aiworkmonitor.mobile.model.GpuMetric
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
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Spacer(Modifier.height(12.dp))
            Text("AI Work Monitor", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text("电脑工作状态与硬件遥测", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
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

@Composable
private fun ConnectionCard(model: MainViewModel) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
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
