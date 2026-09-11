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
    val activeSession: ClaudeSessionState? = null,
    val activeSessions: List<ClaudeSessionState> = emptyList(),
    val sessions: List<ClaudeSessionState> = emptyList(),
)

data class ClaudeSessionState(
    val sessionId: String,
    val projectName: String,
    val projectPath: String,
    val workingDirectory: String? = null,
    val lastActivityAt: String,
    val active: Boolean,
    val displayName: String? = null,
    val model: String? = null,
    val gitBranch: String? = null,
    val lastPrompt: String? = null,
    val processId: Int? = null,
    val status: String? = null,
)

data class ClaudeCommandResult(
    val requestId: String,
    val ok: Boolean,
    val output: String,
    val action: String = "prompt",
    val sessionId: String? = null,
    val model: String? = null,
    val effort: String? = null,
)

data class ActivityItem(
    val provider: String,
    val role: String?,
    val text: String,
    val projectName: String? = null,
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
    val lastCommandResult: ClaudeCommandResult?,
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
                        val activeSession = provider.optJSONObject("activeSession")?.toClaudeSession()
                        val activeSessions = buildList {
                            val activeArray = provider.optJSONArray("activeSessions")
                            if (activeArray != null) for (sessionIndex in 0 until activeArray.length()) {
                                add(activeArray.getJSONObject(sessionIndex).toClaudeSession())
                            }
                        }
                        val sessions = buildList {
                            val sessionArray = provider.optJSONArray("sessions")
                            if (sessionArray != null) for (sessionIndex in 0 until sessionArray.length()) {
                                add(sessionArray.getJSONObject(sessionIndex).toClaudeSession())
                            }
                        }
                        add(
                            ProviderState(
                                name = key,
                                running = provider.optBoolean("running"),
                                mode = provider.optString("mode").ifBlank { null },
                                activeSession = activeSession,
                                activeSessions = activeSessions,
                                sessions = sessions,
                            ),
                        )
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
                                role = event.optionalString("role"),
                                text = event.optString("text"),
                                projectName = event.optionalString("projectName"),
                            ),
                        )
                    }
                }
            }

            val results = item.optJSONArray("commandResults")
            val lastResult = if (results != null && results.length() > 0) {
                val result = results.getJSONObject(results.length() - 1)
                ClaudeCommandResult(
                    requestId = result.optString("requestId"),
                    ok = result.optBoolean("ok"),
                    output = result.optString("output"),
                    action = result.optString("action", "prompt"),
                    sessionId = result.optString("sessionId").ifBlank { null },
                    model = result.optString("model").ifBlank { null },
                    effort = result.optString("effort").ifBlank { null },
                )
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

private fun JSONObject.toClaudeSession(): ClaudeSessionState = ClaudeSessionState(
    sessionId = optString("sessionId"),
    projectName = optString("projectName"),
    projectPath = optString("projectPath"),
    workingDirectory = optionalString("workingDirectory"),
    lastActivityAt = optString("lastActivityAt"),
    active = optBoolean("active"),
    displayName = optionalString("displayName") ?: optionalString("slug"),
    model = optionalString("model"),
    gitBranch = optionalString("gitBranch"),
    lastPrompt = optionalString("lastPrompt"),
    processId = if (has("processId") && !isNull("processId")) optInt("processId") else null,
    status = optionalString("status"),
)

private fun JSONObject.optionalString(name: String): String? {
    if (!has(name) || isNull(name)) return null
    return optString(name).trim().takeIf { it.isNotEmpty() && !it.equals("null", ignoreCase = true) }
}
