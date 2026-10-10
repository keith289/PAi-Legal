package com.pailegal.companion

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import org.json.JSONObject
import java.io.IOException

class MainActivity : AppCompatActivity() {

    private lateinit var etServerUrl: EditText
    private lateinit var etPairingToken: EditText
    private lateinit var btnConnect: Button
    private lateinit var rvCases: RecyclerView
    private var client: CompanionApiClient? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        etServerUrl = findViewById(R.id.etServerUrl)
        etPairingToken = findViewById(R.id.etPairingToken)
        btnConnect = findViewById(R.id.btnConnect)
        rvCases = findViewById(R.id.rvCases)

        rvCases.layoutManager = LinearLayoutManager(this)

        btnConnect.setOnClickListener {
            val url = etServerUrl.text.toString().trim()
            val token = etPairingToken.text.toString().trim()

            if (url.isEmpty() || token.isEmpty()) {
                Toast.makeText(this, "Please enter Server URL and Token", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            client = CompanionApiClient(url, token)
            loadCases()
        }
    }

    private fun loadCases() {
        client?.getCases(object : CompanionApiClient.ApiCallback {
            override fun onSuccess(response: String) {
                runOnUiThread {
                    val json = JSONObject(response)
                    val casesArray = json.getJSONArray("cases")
                    val casesList = mutableListOf<JSONObject>()
                    for (i in 0 until casesArray.length()) {
                        casesList.add(casesArray.getJSONObject(i))
                    }
                    rvCases.adapter = CaseAdapter(casesList) { caseObj ->
                        val intent = Intent(this@MainActivity, CaseViewActivity::class.java).apply {
                            putExtra("server_url", etServerUrl.text.toString().trim())
                            putExtra("token", etPairingToken.text.toString().trim())
                            putExtra("case_id", caseObj.getString("case_id"))
                            putExtra("case_name", caseObj.getString("name"))
                        }
                        startActivity(intent)
                    }
                    Toast.makeText(this@MainActivity, "Connected: Found ${casesList.size} cases", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onError(error: String) {
                runOnUiThread {
                    Toast.makeText(this@MainActivity, "Error: $error", Toast.LENGTH_LONG).show()
                }
            }
        })
    }
}
