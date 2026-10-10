package com.pailegal.companion

import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException

class CompanionApiClient(private val baseUrl: String, private val token: String) {

    private val client = OkHttpClient()
    private val JSON = "application/json; charset=utf-8".toMediaType()

    interface ApiCallback {
        fun onSuccess(response: String)
        fun onError(error: String)
    }

    fun getCases(callback: ApiCallback) {
        val request = Request.Builder()
            .url("$baseUrl/api/cases")
            .addHeader("Authorization", "Bearer $token")
            .get()
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback.onError(e.message ?: "Network error")
            }

            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string() ?: ""
                if (response.isSuccessful) {
                    callback.onSuccess(body)
                } else {
                    callback.onError("HTTP ${response.code}: $body")
                }
            }
        })
    }

    fun getCaseFiles(caseId: String, callback: ApiCallback) {
        val request = Request.Builder()
            .url("$baseUrl/api/cases/$caseId/files")
            .addHeader("Authorization", "Bearer $token")
            .get()
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback.onError(e.message ?: "Network error")
            }

            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string() ?: ""
                if (response.isSuccessful) {
                    callback.onSuccess(body)
                } else {
                    callback.onError("HTTP ${response.code}: $body")
                }
            }
        })
    }

    fun getFileContent(caseId: String, filename: String, callback: ApiCallback) {
        val request = Request.Builder()
            .url("$baseUrl/api/cases/$caseId/files/$filename")
            .addHeader("Authorization", "Bearer $token")
            .get()
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback.onError(e.message ?: "Network error")
            }

            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string() ?: ""
                if (response.isSuccessful) {
                    callback.onSuccess(body)
                } else {
                    callback.onError("HTTP ${response.code}: $body")
                }
            }
        })
    }

    fun uploadEvidence(caseId: String, filename: String, textContent: String, callback: ApiCallback) {
        val payload = JSONObject().apply {
            put("filename", filename)
            put("text", textContent)
        }
        val requestBody = payload.toString().toRequestBody(JSON)
        val request = Request.Builder()
            .url("$baseUrl/api/cases/$caseId/evidence")
            .addHeader("Authorization", "Bearer $token")
            .post(requestBody)
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback.onError(e.message ?: "Network error")
            }

            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string() ?: ""
                if (response.isSuccessful) {
                    callback.onSuccess(body)
                } else {
                    callback.onError("HTTP ${response.code}: $body")
                }
            }
        })
    }
}
