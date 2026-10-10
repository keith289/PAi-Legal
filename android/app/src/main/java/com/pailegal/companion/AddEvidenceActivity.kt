package com.pailegal.companion

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

class AddEvidenceActivity : AppCompatActivity() {

    private lateinit var etFilename: EditText
    private lateinit var etContent: EditText
    private lateinit var btnUpload: Button

    private var caseId: String = ""
    private var serverUrl: String = ""
    private var token: String = ""
    private var client: CompanionApiClient? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_add_evidence)

        etFilename = findViewById(R.id.etFilename)
        etContent = findViewById(R.id.etContent)
        btnUpload = findViewById(R.id.btnUpload)

        caseId = intent.getStringExtra("case_id") ?: ""
        serverUrl = intent.getStringExtra("server_url") ?: ""
        token = intent.getStringExtra("token") ?: ""

        client = CompanionApiClient(serverUrl, token)

        btnUpload.setOnClickListener {
            val filename = etFilename.text.toString().trim()
            val content = etContent.text.toString().trim()

            if (filename.isEmpty() || content.isEmpty()) {
                Toast.makeText(this, "Filename and content required", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            client?.uploadEvidence(caseId, filename, content, object : CompanionApiClient.ApiCallback {
                override fun onSuccess(response: String) {
                    runOnUiThread {
                        Toast.makeText(this@AddEvidenceActivity, "Evidence uploaded successfully!", Toast.LENGTH_SHORT).show()
                        finish()
                    }
                }

                override fun onError(error: String) {
                    runOnUiThread {
                        Toast.makeText(this@AddEvidenceActivity, "Upload failed: $error", Toast.LENGTH_LONG).show()
                    }
                }
            })
        }
    }
}
