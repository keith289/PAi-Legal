import Foundation

struct CaseItem: Identifiable, Codable {
    var id: String { case_id }
    let case_id: String
    let name: String
    let status: String
    let document_count: Int
}

struct CasesResponse: Codable {
    let cases: [CaseItem]
}

struct CaseFileItem: Identifiable, Codable {
    var id: String { name }
    let name: String
    let stem: String
    let bytes: Int64
    let kind: String
}

struct CaseFilesResponse: Codable {
    let case_id: String
    let files: [CaseFileItem]
}

struct FileContentResponse: Codable {
    let case_id: String
    let filename: String
    let content: String
}

class CompanionAPIClient: ObservableObject {
    @Published var baseURL: String = ""
    @Published var token: String = ""

    init(baseURL: String = "", token: String = "") {
        self.baseURL = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        self.token = token.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func fetchCases(completion: @escaping (Result<[CaseItem], Error>) -> Void) {
        guard let url = URL(string: "\(baseURL)/api/cases") else {
            completion(.failure(NSError(domain: "InvalidURL", code: 400)))
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")

        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error = error {
                completion(.failure(error))
                return
            }
            guard let data = data else {
                completion(.failure(NSError(domain: "NoData", code: 404)))
                return
            }
            do {
                let decoded = try JSONDecoder().decode(CasesResponse.self, from: data)
                completion(.success(decoded.cases))
            } catch {
                completion(.failure(error))
            }
        }.resume()
    }

    func fetchCaseFiles(caseID: String, completion: @escaping (Result<[CaseFileItem], Error>) -> Void) {
        guard let url = URL(string: "\(baseURL)/api/cases/\(caseID)/files") else {
            completion(.failure(NSError(domain: "InvalidURL", code: 400)))
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")

        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error = error {
                completion(.failure(error))
                return
            }
            guard let data = data else {
                completion(.failure(NSError(domain: "NoData", code: 404)))
                return
            }
            do {
                let decoded = try JSONDecoder().decode(CaseFilesResponse.self, from: data)
                completion(.success(decoded.files))
            } catch {
                completion(.failure(error))
            }
        }.resume()
    }

    func fetchFileContent(caseID: String, filename: String, completion: @escaping (Result<String, Error>) -> Void) {
        guard let url = URL(string: "\(baseURL)/api/cases/\(caseID)/files/\(filename)") else {
            completion(.failure(NSError(domain: "InvalidURL", code: 400)))
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")

        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error = error {
                completion(.failure(error))
                return
            }
            guard let data = data else {
                completion(.failure(NSError(domain: "NoData", code: 404)))
                return
            }
            do {
                let decoded = try JSONDecoder().decode(FileContentResponse.self, from: data)
                completion(.success(decoded.content))
            } catch {
                completion(.failure(error))
            }
        }.resume()
    }

    func uploadEvidence(caseID: String, filename: String, textContent: String, completion: @escaping (Result<Void, Error>) -> Void) {
        guard let url = URL(string: "\(baseURL)/api/cases/\(caseID)/evidence") else {
            completion(.failure(NSError(domain: "InvalidURL", code: 400)))
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")

        let payload: [String: String] = ["filename": filename, "text": textContent]
        guard let bodyData = try? JSONSerialization.data(withJSONObject: payload) else {
            completion(.failure(NSError(domain: "InvalidPayload", code: 400)))
            return
        }
        request.httpBody = bodyData

        URLSession.shared.dataTask(with: request) { _, response, error in
            if let error = error {
                completion(.failure(error))
                return
            }
            completion(.success(()))
        }.resume()
    }
}
