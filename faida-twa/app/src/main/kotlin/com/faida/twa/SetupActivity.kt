package com.faida.twa

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.faida.twa.MainActivity.Companion.KEY_API_TOKEN
import com.faida.twa.MainActivity.Companion.KEY_SERVER_URL
import com.faida.twa.MainActivity.Companion.PREFS_NAME

/**
 * Shown once on first launch.
 * User enters:
 *   1. Server URL  — e.g. https://faida-app.onrender.com
 *   2. API Token   — copied from Profil → Code API in the web app
 *
 * Both values are saved to SharedPreferences and read by SmsReceiver.
 */
class SetupActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_setup)

        val etUrl   = findViewById<EditText>(R.id.etServerUrl)
        val etToken = findViewById<EditText>(R.id.etApiToken)
        val btnSave = findViewById<Button>(R.id.btnSave)

        // Pre-fill with any previously stored values
        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        etUrl.setText(prefs.getString(KEY_SERVER_URL, ""))
        etToken.setText(prefs.getString(KEY_API_TOKEN, ""))

        btnSave.setOnClickListener {
            val url   = etUrl.text.toString().trim().trimEnd('/')
            val token = etToken.text.toString().trim()

            if (url.isEmpty() || (!url.startsWith("http://") && !url.startsWith("https://"))) {
                Toast.makeText(this, "URL invalide — commencez par https://", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            if (token.length < 10) {
                Toast.makeText(this, "Code API invalide — copiez-le depuis votre profil Faida", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            prefs.edit()
                .putString(KEY_SERVER_URL, url)
                .putString(KEY_API_TOKEN, token)
                .apply()

            Toast.makeText(this, "Configuration enregistrée ✓", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, MainActivity::class.java))
            finish()
        }
    }
}
