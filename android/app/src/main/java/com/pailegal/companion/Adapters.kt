package com.pailegal.companion

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import org.json.JSONObject

class CaseAdapter(
    private val cases: List<JSONObject>,
    private val onItemClick: (JSONObject) -> Unit
) : RecyclerView.Adapter<CaseAdapter.CaseViewHolder>() {

    class CaseViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val tvCaseName: TextView = itemView.findViewById(R.id.tvCaseName)
        val tvCaseDetail: TextView = itemView.findViewById(R.id.tvCaseDetail)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): CaseViewHolder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_case, parent, false)
        return CaseViewHolder(view)
    }

    override fun onBindViewHolder(holder: CaseViewHolder, position: Int) {
        val item = cases[position]
        val caseId = item.optString("case_id", "")
        val name = item.optString("name", "")
        val docCount = item.optInt("document_count", 0)

        holder.tvCaseName.text = "$caseId — $name"
        holder.tvCaseDetail.text = "Documents: $docCount"

        holder.itemView.setOnClickListener { onItemClick(item) }
    }

    override fun getItemCount(): Int = cases.size
}

class FileAdapter(
    private val files: List<JSONObject>,
    private val onItemClick: (JSONObject) -> Unit
) : RecyclerView.Adapter<FileAdapter.FileViewHolder>() {

    class FileViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val tvFileName: TextView = itemView.findViewById(R.id.tvFileName)
        val tvFileDetail: TextView = itemView.findViewById(R.id.tvFileDetail)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): FileViewHolder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_file, parent, false)
        return FileViewHolder(view)
    }

    override fun onBindViewHolder(holder: FileViewHolder, position: Int) {
        val item = files[position]
        val name = item.optString("name", "")
        val bytes = item.optLong("bytes", 0)
        val kind = item.optString("kind", "")

        holder.tvFileName.text = name
        holder.tvFileDetail.text = "Type: $kind | Size: ${bytes}B"

        holder.itemView.setOnClickListener { onItemClick(item) }
    }

    override fun getItemCount(): Int = files.size
}
