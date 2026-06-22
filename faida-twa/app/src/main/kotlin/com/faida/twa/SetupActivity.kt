package com.faida.twa

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.faida.twa.MainActivity.Companion.KEY_API_TOKEN
import com.faida.twa.MainActivity.Companion.PREFS_NAME

class SetupActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_setup)

        val etToken = findViewById<EditText>(R.id.etApiToken)
        val btnSave = findViewById<Button>(R.id.btnSave)

        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        etToken.setText(prefs.getString(KEY_API_TOKEN, ""))

        btnSave.setOnClickListener {
            val token = etToken.text.toString().trim()

            if (token.length < 10) {
                Toast.makeText(
                    this,
                    "Code invalide — copiez-le depuis votre profil Faida",
                    Toast.LENGTH_SHORT
                ).show()
                return@setOnClickListener
            }

            prefs.edit().putString(KEY_API_TOKEN, token).apply()
            Toast.makeText(this, "Connecté ✓", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, MainActivity::class.java))
            finish()
        }
    }
}
