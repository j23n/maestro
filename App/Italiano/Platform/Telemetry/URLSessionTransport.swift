import Foundation

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// The real `HTTPTransport` for the study and review endpoints (docs/12). Ephemeral session: no cookies, no cache.
struct URLSessionTransport: HTTPTransport {
    private let session: URLSession

    init(session: URLSession = URLSession(configuration: .ephemeral)) { self.session = session }

    func send(_ request: HTTPRequestSpec) async throws -> Int {
        var r = URLRequest(url: request.url)
        r.httpMethod = request.method
        r.httpBody = request.body
        r.timeoutInterval = 30
        for (k, v) in request.headers { r.setValue(v, forHTTPHeaderField: k) }
        let (_, response) = try await session.data(for: r)
        return (response as? HTTPURLResponse)?.statusCode ?? 0
    }
}
