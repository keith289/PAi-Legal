import SwiftUI

struct CaseDetailView: View {
    let client: CompanionAPIClient
    let caseItem: CaseItem

    @State private var files: [CaseFileItem] = []
    @State private var selectedFileContent: String = ""
    @State private var selectedFileName: String = ""
    @State private var isShowingContentAlert: Bool = false
    @State private var isLoading: Bool = false
    @State private var errorMessage: String = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(caseItem.name)
                    .font(.title2)
                    .fontWeight(.bold)
                    .foregroundColor(Color(red: 0.09, green: 0.65, blue: 1.0))
                Text("Case ID: \(caseItem.case_id)")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
            }
            .padding(.horizontal)

            NavigationLink(destination: AddEvidenceView(client: client, caseID: caseItem.case_id)) {
                HStack {
                    Spacer()
                    Image(systemName: "doc.badge.plus")
                    Text("Add Evidence / Quick Note")
                        .fontWeight(.semibold)
                    Spacer()
                }
                .padding()
                .background(Color(red: 0.09, green: 0.65, blue: 1.0))
                .foregroundColor(.white)
                .cornerRadius(8)
            }
            .padding(.horizontal)

            Text("Case Files:")
                .font(.headline)
                .padding(.horizontal)
                .padding(.top, 8)

            if isLoading {
                ProgressView()
                    .padding()
            } else if !errorMessage.isEmpty {
                Text(errorMessage)
                    .foregroundColor(.red)
                    .padding()
            } else {
                List(files) { file in
                    Button(action: { loadFileContent(file: file) }) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(file.name)
                                .font(.body)
                                .fontWeight(.medium)
                                .foregroundColor(.primary)
                            Text("Type: \(file.kind) | Size: \(file.bytes) bytes")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                    }
                }
                .listStyle(PlainListStyle())
            }
        }
        .navigationTitle(caseItem.case_id)
        .navigationBarTitleDisplayMode(.inline)
        .onAppear(perform: loadFiles)
        .alert(isPresented: $isShowingContentAlert) {
            Alert(
                title: Text(selectedFileName),
                message: Text(selectedFileContent),
                dismissButton: .default(Text("OK"))
            )
        }
    }

    private func loadFiles() {
        isLoading = true
        errorMessage = ""
        client.fetchCaseFiles(caseID: caseItem.case_id) { result in
            DispatchQueue.main.async {
                isLoading = false
                switch result {
                case .success(let fetchedFiles):
                    self.files = fetchedFiles
                case .failure(let error):
                    self.errorMessage = "Failed to load files: \(error.localizedDescription)"
                }
            }
        }
    }

    private func loadFileContent(file: CaseFileItem) {
        selectedFileName = file.name
        client.fetchFileContent(caseID: caseItem.case_id, filename: file.name) { result in
            DispatchQueue.main.async {
                switch result {
                case .success(let content):
                    self.selectedFileContent = content
                    self.isShowingContentAlert = true
                case .failure(let error):
                    self.selectedFileContent = "Error reading file: \(error.localizedDescription)"
                    self.isShowingContentAlert = true
                }
            }
        }
    }
}
