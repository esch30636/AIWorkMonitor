package com.aiworkmonitor.mobile.storage

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.nio.ByteBuffer
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class SavedConnection(
    val id: String,
    val name: String,
    val relayUrl: String,
    val token: String,
    val lastConnectedAt: Long,
)

class ConnectionStore(context: Context) {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    private val tokenCipher = TokenCipher()

    @Synchronized
    fun load(): List<SavedConnection> {
        val raw = preferences.getString(PROFILES_KEY, null) ?: return emptyList()
        return runCatching {
            val array = JSONArray(raw)
            buildList {
                for (index in 0 until array.length()) {
                    val item = array.getJSONObject(index)
                    runCatching {
                        SavedConnection(
                            id = item.getString("id"),
                            name = item.getString("name"),
                            relayUrl = item.getString("relayUrl"),
                            token = tokenCipher.decrypt(item.getString("encryptedToken")),
                            lastConnectedAt = item.optLong("lastConnectedAt", 0L),
                        )
                    }.getOrNull()?.let(::add)
                }
            }.sortedByDescending { it.lastConnectedAt }
        }.getOrDefault(emptyList())
    }

    @Synchronized
    fun save(name: String, relayUrl: String, token: String): SavedConnection {
        val normalizedUrl = normalizeUrl(relayUrl)
        val current = load()
        val existing = current.firstOrNull { normalizeUrl(it.relayUrl) == normalizedUrl }
        val saved = SavedConnection(
            id = existing?.id ?: UUID.randomUUID().toString(),
            name = name.trim(),
            relayUrl = relayUrl.trim(),
            token = token,
            lastConnectedAt = System.currentTimeMillis(),
        )
        persist((current.filterNot { it.id == saved.id } + saved).sortedByDescending { it.lastConnectedAt })
        return saved
    }

    private fun persist(connections: List<SavedConnection>) {
        val array = JSONArray()
        connections.forEach { connection ->
            array.put(
                JSONObject()
                    .put("id", connection.id)
                    .put("name", connection.name)
                    .put("relayUrl", connection.relayUrl)
                    .put("encryptedToken", tokenCipher.encrypt(connection.token))
                    .put("lastConnectedAt", connection.lastConnectedAt),
            )
        }
        preferences.edit().putString(PROFILES_KEY, array.toString()).apply()
    }

    private fun normalizeUrl(url: String): String = url.trim().trimEnd('/').lowercase()

    private companion object {
        const val PREFERENCES_NAME = "saved_connections"
        const val PROFILES_KEY = "profiles_json"
    }
}

private class TokenCipher {
    private val keyStore = KeyStore.getInstance(ANDROID_KEY_STORE).apply { load(null) }

    fun encrypt(value: String): String {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        val payload = ByteBuffer.allocate(1 + cipher.iv.size + encrypted.size)
            .put(cipher.iv.size.toByte())
            .put(cipher.iv)
            .put(encrypted)
            .array()
        return Base64.encodeToString(payload, Base64.NO_WRAP)
    }

    fun decrypt(value: String): String {
        val payload = ByteBuffer.wrap(Base64.decode(value, Base64.NO_WRAP))
        val ivLength = payload.get().toInt() and 0xFF
        require(ivLength in 12..16 && payload.remaining() > ivLength) { "Invalid encrypted token" }
        val iv = ByteArray(ivLength).also(payload::get)
        val encrypted = ByteArray(payload.remaining()).also(payload::get)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(128, iv))
        return cipher.doFinal(encrypted).toString(Charsets.UTF_8)
    }

    private fun getOrCreateKey(): SecretKey {
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEY_STORE).run {
            init(
                KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .build(),
            )
            generateKey()
        }
    }

    private companion object {
        const val ANDROID_KEY_STORE = "AndroidKeyStore"
        const val KEY_ALIAS = "ai_work_monitor_connection_token_v1"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
    }
}
