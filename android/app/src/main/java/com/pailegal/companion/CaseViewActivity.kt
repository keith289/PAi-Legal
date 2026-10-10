package com.pailegal.companion

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import org.json.JSONObject

class CaseViewActivity : AppCompatActivity() {

    private lateinit var tvCaseHeader: TextView
    private lateinit var btnAddEvidence: Button
    private lateinit var rvFiles: RecyclerView

    private var caseId: String = ""
    private var caseName: String = ""
    private var serverUrl: String = ""
    private var token: String = ""
    private var client: CompanionApiClient? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_case_view)

        tvCaseHeader = findViewById(R.id.tvCaseHeader)
        btnAddEvidence = findViewById(R.id.btnAddEvidence)
        rvFiles = findViewById(R.id.rvFiles)

        caseId = intent.getStringExtra("case_id") ?: ""
        caseName = intent.getStringExtra("case_name") ?: ""
        serverUrl = intent.getStringExtra("server_url") ?: ""
        token = intent.getStringExtra("token") ?: ""

        tvCaseHeader.text = "$caseId: $caseName"
        client = CompanionApiClient(serverUrl, token)

        rvFiles.layoutManager = LinearLayoutManager(this)

        btnAddEvidence.setOnClickListener {
            val intent = Intent(this, AddEvidenceActivity::class.java).apply {
                putExtra("server_url", serverUrl)
                putExtra("token", token)
                putExtra("case_id", caseId)
            }
            startActivity(intent)
        }

        loadFiles()
    }

    override fun onResume() {
        super.onResume()
        loadFiles()
    }

    private fun loadFiles() {
        client?.getCaseFiles(caseId, object : CompanionApiClient.ApiCallback {
            override fun onSuccess(response: String) {
                runOnUiThread {
                    val json = JSONObject(response)
                    val filesArray = json.getJSONArray("files")
                    val filesList = mutableListOf<JSONObject>()
                    for (i in 0 until filesArray.length()) {
                        filesList.add(filesArray.getJSONObject(i))
                    }
                    rvFiles.adapter = FileAdapter(filesList) { fileObj ->
                        val filename = fileObj.getString("name")
                        client?.getFileContent(caseId, filename, object : CompanionApiClient.ApiCallback {
                            override fun onSuccess(contentResponse: String) {
                                runOnUiThread {
                                    val contentJson = JSONObject(contentResponse)
                                    val text = contentJson.optString("content", "No text content")
                                    Toast.makeText(this@CaseViewActivity, "File: $filename\n\n$text", Toast.LENGTH_LONG).show()
                                }
                            }

                            override fun onError(error: String) {
                                runOnUiThread {
                                    Toast.makeText(this@CaseViewActivity, "Failed to read file: $error", Toast.LENGTH_SHORT).show()
                                }
                            }
                        })
                    }
                }
            }

            override fun onError(error: String) {
                runOnUiThread {
                    Toast.makeText(this@CaseViewActivity, "Error loading files: $error", Toast.LENGTH_SHORT).show()
                }
            }
        })
    }
}
