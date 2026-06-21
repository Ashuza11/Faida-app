package com.faida.twa

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import com.faida.twa.MainActivity.Companion.KEY_API_TOKEN
import com.faida.twa.MainActivity.Companion.KEY_SERVER_URL
import com.faida.twa.MainActivity.Companion.PREFS_NAME
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Sends parsed SMS data to the Faida server via POST /api/v1/sms-ingest.
 * Authenticates using the personal API token stored in SharedPreferences.
 * Shows a local notification with the result.
 */
object FaidaApiClient {

    private const val TAG = "FaidaApiClient"
    private const val CHANNEL_ID = "faida_sms_capture"
    private const val CHANNEL_NAME = "Faida — Capture SMS"

    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    fun postSms(context: Context, sender: String, body: String) {
        scope.launch {
            try {
                val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                val serverUrl = prefs.getString(KEY_SERVER_URL, "").orEmpty().trimEnd('/')
                val apiToken  = prefs.getString(KEY_API_TOKEN, "").orEmpty()

                if (serverUrl.isEmpty() || apiToken.isEmpty()) {
                    Log.w(TAG, "Server URL or API token not configured — skipping SMS")
                    return@launch
                }

                val jsonBody = JSONObject().apply {
                    put("sender", sender)
                    put("body", body)
                }.toString()

                val request = Request.Builder()
                    .url("$serverUrl/api/v1/sms-ingest")
                    .addHeader("X-Api-Token", apiToken)
                    .addHeader("Content-Type", "application/json")
                    .post(jsonBody.toRequestBody("application/json".toMediaType()))
                    .build()

                val response = http.newCall(request).execute()
                val responseBody = response.body?.string() ?: "{}"
                Log.d(TAG, "Response ${response.code}: $responseBody")

                val result = runCatching { JSONObject(responseBody) }.getOrElse { JSONObject() }

                val message = when {
                    !response.isSuccessful -> "Erreur serveur (${response.code}). Vérifiez votre connexion."
                    else -> when (result.optString("type")) {
                        "sale" -> {
                            val network = result.optString("network", "").replaceFirstChar { it.uppercase() }
                            val qty     = result.optInt("quantity", 0)
                            val client  = result.optString("client", "inconnu")
                            "Vente enregistrée: ${qty}U $network → $client"
                        }
                        "purchase" -> {
                            val network  = result.optString("network", "").replaceFirstChar { it.uppercase() }
                            val qty      = result.optInt("quantity", 0)
                            val balance  = result.optDouble("new_balance", 0.0).toInt()
                            "Achat enregistré: +${qty}U $network (solde: ${balance}U)"
                        }
                        "unknown" -> return@launch  // silently ignore unrecognised SMS
                        else -> result.optString("error", "SMS traité")
                    }
                }

                showNotification(context, message)

            } catch (e: Exception) {
                Log.e(TAG, "Failed to post SMS to Faida", e)
                showNotification(context, "Faida hors ligne — vente non enregistrée automatiquement")
            }
        }
    }

    private fun showNotification(context: Context, message: String) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID, CHANNEL_NAME, NotificationManager.IMPORTANCE_DEFAULT
            ).apply { description = "Résultats de la capture SMS automatique" }
            manager.createNotificationChannel(channel)
        }

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("Faida")
            .setContentText(message)
            .setStyle(NotificationCompat.BigTextStyle().bigText(message))
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .build()

        manager.notify(System.currentTimeMillis().toInt(), notification)
    }
}
