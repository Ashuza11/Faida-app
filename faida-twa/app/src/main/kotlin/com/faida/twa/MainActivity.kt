package com.faida.twa

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.google.androidbrowserhelper.trusted.TwaLauncher

class MainActivity : AppCompatActivity() {

    private val SMS_PERMISSION_CODE = 101

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        val apiToken = prefs.getString(KEY_API_TOKEN, "").orEmpty().trim()

        // First launch: show setup screen to enter the API token
        if (apiToken.isEmpty()) {
            startActivity(Intent(this, SetupActivity::class.java))
            finish()
            return
        }

        requestMissingPermissions()
    }

    private fun requestMissingPermissions() {
        val needed = mutableListOf<String>()

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS)
            != PackageManager.PERMISSION_GRANTED) {
            needed += Manifest.permission.RECEIVE_SMS
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_SMS)
            != PackageManager.PERMISSION_GRANTED) {
            needed += Manifest.permission.READ_SMS
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED) {
            needed += Manifest.permission.POST_NOTIFICATIONS
        }

        if (needed.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, needed.toTypedArray(), SMS_PERMISSION_CODE)
        } else {
            launchTwa()
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.none { it == PackageManager.PERMISSION_DENIED }) {
            Toast.makeText(this, "Capture SMS activée ✓", Toast.LENGTH_SHORT).show()
        } else {
            Toast.makeText(
                this,
                "Permission SMS refusée — la capture automatique ne fonctionnera pas",
                Toast.LENGTH_LONG
            ).show()
        }
        launchTwa()
    }

    private fun launchTwa() {
        TwaLauncher(this).launch(Uri.parse(BuildConfig.SERVER_URL))
    }

    companion object {
        const val PREFS_NAME    = "faida_prefs"
        const val KEY_API_TOKEN = "api_token"
    }
}
