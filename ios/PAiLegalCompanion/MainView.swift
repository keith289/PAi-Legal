import SwiftUI

struct MainView: View {
    @State private var serverURL: String = ""
    @State private var pairingToken: String = ""
    @State private var isConnected: Bool = false
    @State private var cases: [CaseItem] = []
    @State private var errorMessage: String = ""
    @State private var isLoading: Bool = false

    @StateObject private var client = CompanionAPIClient()

    var body: some View {
        NavigationView {
            VStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("PAi Legal Companion")
                        .font(.largeTitle)
                        .fontWeight(.bold)
                        .foregroundColor(Color(red: 0.09, green: 0.65, blue: 1.0))

                    TextField("Desktop Server URL (e.g. http://192.168.1.10:8088)", text: $serverURL)
                        .textFieldStyle(RoundedBorderTextFieldStyle())
                        .autocapitalization(.none)
                        .disableAutocorrection(true)

                    SecureField("Pairing Token", text: $pairingToken)
                        .textFieldStyle(RoundedBorderTextFieldStyle())

                    Button(action: connectAndLoadCases) {
                        HStack {
                            Spacer()
                            if isLoading {
                                ProgressView()
                                    .progressViewStyle(CircularProgressViewStyle(tint: .white))
                            } else {
                                Text("Connect to Desktop Workspace")
                                    .fontWeight(.semibold)
                            }
                            Spacer()
                        }
                        .padding()
                        .background(Color(red: 0.09, green: 0.65, blue: 1.0))
                        .foregroundColor(.white)
                        .cornerRadius(8)
                    }
                }
                .padding()

                if !errorMessage.isEmpty {
                    Text(errorMessage)
                        .foregroundColor(.red)
                        .font(.subheadline)
                        .padding(.horizontal)
                }

                List(cases) { item in
                    NavigationLink(destination: CaseDetailView(client: client, caseItem: item)) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("\(item.case_id) — \(item.name)")
                                .font(.headline)
                                .foregroundColor(.primary)
                            Text("Documents: \(item.document_count) | Status: \(item.status)")
                                .font(.subheadline)
                                .foregroundColor(.secondary)
                        }
                        .padding(.vertical, 4)
                    }
                }
                .listStyle(PlainListStyle())
            }
            .navigationBarHidden(true)
        }
    }

    private func connectAndLoadCases() {
        errorMessage = ""
        isLoading = true
        client.baseURL = serverURL
        client.token = pairingToken

        client.fetchCases { result in
            DispatchQueue.main.async {
                isLoading = false
                switch result {
                case .success(let fetchedCases):
                    self.cases = fetchedCases
                    self.isConnected = true
                case .failure(let error):
                    self.errorMessage = "Connection failed: \(error.localizedDescription)"
                }
            }
        }
    }
}
