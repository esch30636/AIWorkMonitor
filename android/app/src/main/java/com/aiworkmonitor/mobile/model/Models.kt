package com.aiworkmonitor.mobile.model

import org.json.JSONObject

data class CpuMetric(
    val usagePercent: Double? = null,
    val temperatureC: Double? = null,
    val powerW: Double? = null,
)

data class MemoryMetric(
    val usedBytes: Long = 0,
    val totalBytes: Long = 0,
    val usagePercent: Double? = null,
)

data class GpuMetric(
    val name: String,
    val usagePercent: Double? = null,
    val temperatureC: Double? = null,
    val powerW: Double? = null,
    val memoryUsedBytes: Long = 0,
    val memoryTotalBytes: Long = 0,
)

data class ProviderState(
    val name: String,
    val running: Boolean,
    val mode: String? = null,
)

data class ActivityItem(
    val provider: String,
    val role: String?,
    val text: String,
)

data class DeviceSnapshot(
    val deviceId: String,
    val name: String,
    val os: String,
    val online: Boolean,
    val lastSeen: String,
    val claudeCommands: Boolean,
    val cpu: CpuMetric,
    val memory: MemoryMetric,
    val gpus: List<GpuMetric>,
    val providers: List<ProviderState>,
    val activity: List<ActivityItem>,
    val lastCommandResult: String?,
)

private fun JSONObject.optionalDouble(name: String): Double? =
    if (has(name) && !isNull(name)) optDouble(name) else null

fun parseSnapshot(message: String): List<DeviceSnapshot> {
    val envelope = JSONObject(message)
    if (envelope.optString("type") != "snapshot") return emptyList()
    val array = envelope.getJSONObject("payload").optJSONArray("devices") ?: return emptyList()
    return buildList {
        for (index in 0 until array.length()) {
            val item = array.getJSONObject(index)
            val telemetry = item.optJSONObject("telemetry") ?: JSONObject()
            val cpu = telemetry.optJSONObject("cpu") ?: JSONObject()
            val memory = telemetry.optJSONObject("memory") ?: JSONObject()
            val capabilities = item.optJSONObject("capabilities") ?: JSONObject()

            val gpuItems = buildList {
                val gpus = telemetry.optJSONArray("gpus")
                if (gpus != null) for (gpuIndex in 0 until gpus.length()) {
                    val gpu = gpus.getJSONObject(gpuIndex)
                    add(
                        GpuMetric(
                            name = gpu.optString("name", "GPU"),
                            usagePercent = gpu.optionalDouble("usagePercent"),
                            temperatureC = gpu.optionalDouble("temperatureC"),
                            powerW = gpu.optionalDouble("powerW"),
                            memoryUsedBytes = gpu.optLong("memoryUsedBytes"),
                            memoryTotalBytes = gpu.optLong("memoryTotalBytes"),
                        ),
                    )
                }
            }

            val providerItems = buildList {
                val providers = item.optJSONObject("providers")
                if (providers != null) {
                    val keys = providers.keys()
                    while (keys.hasNext()) {
                        val key = keys.next()
                        val provider = providers.getJSONObject(key)
                        add(ProviderState(key, provider.optBoolean("running"), provider.optString("mode").ifBlank { null }))
                    }
                }
            }

            val activityItems = buildList {
                val activity = item.optJSONArray("activity")
                if (activity != null) {
                    val start = maxOf(0, activity.length() - 20)
                    for (eventIndex in start until activity.length()) {
                        val event = activity.getJSONObject(eventIndex)
                        add(
                            ActivityItem(
                                provider = event.optString("provider", "unknown"),
                                role = event.optString("role").ifBlank { null },
                                text = event.optString("text"),
                            ),
                        )
                    }
                }
            }

            val results = item.optJSONArray("commandResults")
            val lastResult = if (results != null && results.length() > 0) {
                results.getJSONObject(results.length() - 1).optString("output").ifBlank { null }
            } else null

            add(
                DeviceSnapshot(
                    deviceId = item.optString("deviceId"),
                    name = item.optString("name", item.optString("deviceId")),
                    os = item.optString("os", "Unknown OS"),
                    online = item.optBoolean("online"),
                    lastSeen = item.optString("lastSeen"),
                    claudeCommands = capabilities.optBoolean("claudeCommands"),
                    cpu = CpuMetric(
                        usagePercent = cpu.optionalDouble("usagePercent"),
                        temperatureC = cpu.optionalDouble("temperatureC"),
                        powerW = cpu.optionalDouble("powerW"),
                    ),
                    memory = MemoryMetric(
                        usedBytes = memory.optLong("usedBytes"),
                        totalBytes = memory.optLong("totalBytes"),
                        usagePercent = memory.optionalDouble("usagePercent"),
                    ),
                    gpus = gpuItems,
                    providers = providerItems,
                    activity = activityItems,
                    lastCommandResult = lastResult,
                ),
            )
        }
    }
}

