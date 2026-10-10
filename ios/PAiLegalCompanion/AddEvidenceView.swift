import SwiftUI

struct AddEvidenceView: View {
    let client: CompanionAPIClient
    let caseID: String

    @Environment(\.presentationMode) var presentationMode
    @State private var filename: String = ""
    @State private var textContent: String = ""
    @State private var isUploading: Bool = false
    @State private var statusMessage: String = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Upload Evidence / Note")
                .font(.title2)
                .fontWeight(.bold)
                .foregroundColor(Color(red: 0.09, green: 0.65, blue: 1.0))

            TextField("Filename (e.g. site_inspection.txt)", text: $filename)
                .textFieldStyle(RoundedBorderTextFieldStyle())

            Text("Content / Notes:")
                .font(.subheadline)
                .foregroundColor(.secondary)

            TextEditor(text: $textContent)
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.gray.opacity(0.3), lineWidth: 1))

            if !statusMessage.isEmpty {
                Text(statusMessage)
                    .foregroundColor(statusMessage.contains("Error") || statusMessage.contains("Failed") ? .red : .green)
                    .font(.footnote)
            }

            Button(action: uploadEvidence) {
                HStack {
                    Spacer()
                    if isUploading {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .white))
                    } else {
                        Text("Upload Evidence to Workspace")
                            .fontWeight(.semibold)
                    }
                    Spacer()
                }
                .padding()
                .background(Color(red: 0.09, green: 0.65, blue: 1.0))
                .foregroundColor(.white)
                .cornerRadius(8)
            }
            .disabled(isUploading)
        }
        .padding()
        .navigationTitle("Upload to \(caseID)")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func uploadEvidence() {
        guard !filename.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !textContent.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            statusMessage = "Filename and content are required."
            return
        }

        isUploading = true
        statusMessage = ""

        client.uploadEvidence(caseID: caseID, filename: filename, textContent: textContent) { result in
            DispatchQueue.main.async {
                isUploading = false
                switch result {
                case .success:
                    statusMessage = "Evidence uploaded successfully!"
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
                        presentationMode.wrappedValue.dismiss()
                    }
                case .failure(let error):
                    statusMessage = "Failed to upload: \(error.localizedDescription)"
                }
            }
        }
    }
}
