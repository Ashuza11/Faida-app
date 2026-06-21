package com.faida.twa

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import android.util.Log

/**
 * Listens for incoming SMS from the 4 DRC airtime networks.
 * Recognised sender IDs (case-insensitive):
 *   "Africell" → AFRICEL
 *   "1000"     → AIRTEL
 *   "e-recharge" → ORANGE
 *   "1449"     → VODACOM
 *
 * All other senders are silently ignored.
 */
class SmsReceiver : BroadcastReceiver() {

    companion object {
        private const val TAG = "FaidaSmsReceiver"

        // The exact sender IDs that DRC telecoms use — checked case-insensitively
        private val KNOWN_SENDERS = setOf(
            "africell",
            "1000",
            "e-recharge",
            "1449",
        )
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return

        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent)
        if (messages.isNullOrEmpty()) return

        // All parts of a multi-part SMS share the same sender
        val sender = messages[0].displayOriginatingAddress ?: return
        if (sender.lowercase() !in KNOWN_SENDERS) return

        // Reassemble multi-part messages in order
        val body = messages.joinToString("") { it.messageBody ?: "" }

        Log.d(TAG, "SMS from $sender: ${body.take(80)}")
        FaidaApiClient.postSms(context, sender, body)
    }
}
