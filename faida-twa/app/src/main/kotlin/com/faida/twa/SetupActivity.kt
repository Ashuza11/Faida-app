package com.faida.twa

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.faida.twa.MainActivity.Companion.KEY_API_TOKEN
import com.faida.twa.MainActivity.Companion.KEY_BUSINESS_ID
import com.faida.twa.MainActivity.Companion.KEY_BUSINESS_LABEL
import com.faida.twa.MainActivity.Companion.PREFS_NAME
import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException

class SetupActivity : AppCompatActivity() {

    private val http = OkHttpClient()

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

            btnSave.isEnabled = false
            btnSave.text = "Chargement des modes…"
            loadBusinesses(token, btnSave)
        }
    }

    private fun loadBusinesses(token: String, button: Button) {
        val request = Request.Builder()
            .url("${BuildConfig.SERVER_URL}/api/v1/android/businesses")
            .addHeader("X-Api-Token", token)
            .get()
            .build()
        http.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, error: IOException) {
                runOnUiThread {
                    resetButton(button)
                    Toast.makeText(
                        this@SetupActivity,
                        "Connexion impossible. Vérifiez Internet.",
                        Toast.LENGTH_LONG,
                    ).show()
                }
            }

            override fun onResponse(call: Call, response: Response) {
                response.use {
                    val payload = runCatching {
                        JSONObject(response.body?.string().orEmpty())
                    }.getOrNull()
                    val modes = payload?.optJSONArray("businesses")
                    runOnUiThread {
                        resetButton(button)
                        if (!response.isSuccessful || modes == null) {
                            Toast.makeText(
                                this@SetupActivity,
                                payload?.optString("error", "Code API invalide")
                                    ?: "Code API invalide",
                                Toast.LENGTH_LONG,
                            ).show()
                            return@runOnUiThread
                        }
                        if (modes.length() == 0) {
                            Toast.makeText(
                                this@SetupActivity,
                                "Aucun mode approuvé disponible.",
                                Toast.LENGTH_LONG,
                            ).show()
                            return@runOnUiThread
                        }
                        val ids = LongArray(modes.length())
                        val labels = Array(modes.length()) { index ->
                            modes.getJSONObject(index).also {
                                ids[index] = it.getLong("id")
                            }.getString("label")
                        }
                        if (labels.size == 1) {
                            saveSelection(token, ids[0], labels[0])
                        } else {
                            AlertDialog.Builder(this@SetupActivity)
                                .setTitle("Mode pour la capture SMS")
                                .setItems(labels) { _, index ->
                                    saveSelection(token, ids[index], labels[index])
                                }
                                .setNegativeButton("Annuler", null)
                                .show()
                        }
                    }
                }
            }
        })
    }

    private fun resetButton(button: Button) {
        button.isEnabled = true
        button.text = "Activer Faida"
    }

    private fun saveSelection(token: String, businessId: Long, label: String) {
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE).edit()
            .putString(KEY_API_TOKEN, token)
            .putLong(KEY_BUSINESS_ID, businessId)
            .putString(KEY_BUSINESS_LABEL, label)
            .apply()
        Toast.makeText(this, "$label connecté ✓", Toast.LENGTH_SHORT).show()
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }
}
