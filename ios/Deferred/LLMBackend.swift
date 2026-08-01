// ⚠️ UNTESTED SCAFFOLD.
//
// The optional LLM layer (plan §11 + doc 02 §6): backends behind one
// protocol, feature-gated by the eval scorecard (gates_resolved.json
// bundled at build time), consuming the same prompts/runtime templates
// the eval harness measures. Every outbound payload is logged to the
// privacy ledger.

import Foundation

struct LLMRequest {
    let task: String  // writing_feedback | mistake_explanation
    let variables: [String: String]
}

protocol LLMBackend {
    var name: String { get }
    func complete(system: String, prompt: String) async throws -> String
}

/// Gates: {task: {backend: {enabled, reason}}} — produced by
/// `python -m evals.harness.run --resolve-gates`, bundled as a resource.
struct Gates: Codable {
    let raw: [String: [String: GateVerdict]]
    struct GateVerdict: Codable {
        let enabled: Bool
        let reason: String
    }

    static func load() -> Gates {
        guard let url = Bundle.main.url(forResource: "gates_resolved", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let raw = try? JSONDecoder().decode([String: [String: GateVerdict]].self, from: data)
        else { return Gates(raw: [:]) }
        return Gates(raw: raw)
    }

    func allows(task: String, backend: String) -> Bool {
        // Cloud backends are always allowed (quality reference); only
        // on-device backends are gated.
        backend == "anthropic" || raw[task]?[backend]?.enabled == true
    }
}

final class AnthropicBackend: LLMBackend {
    let name = "anthropic"
    let apiKey: String  // user-supplied, stored in Keychain by Settings

    init(apiKey: String) { self.apiKey = apiKey }

    func complete(system: String, prompt: String) async throws -> String {
        var request = URLRequest(url: URL(string: "https://api.anthropic.com/v1/messages")!)
        request.httpMethod = "POST"
        request.setValue(apiKey, forHTTPHeaderField: "x-api-key")
        request.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")
        request.setValue("application/json", forHTTPHeaderField: "content-type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "model": "claude-sonnet-5",
            "max_tokens": 1500,
            "system": system,
            "messages": [["role": "user", "content": prompt]],
        ])
        let (data, _) = try await URLSession.shared.data(for: request)
        let parsed = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let content = parsed?["content"] as? [[String: Any]] ?? []
        return content.compactMap { $0["text"] as? String }.joined()
    }
}

#if canImport(FoundationModels)
    import FoundationModels

    /// On-device tier — only reachable when Gates.allows(task, "apple_fm").
    final class AppleFMBackend: LLMBackend {
        let name = "apple_fm"

        static var isAvailable: Bool {
            SystemLanguageModel.default.availability == .available
        }

        func complete(system: String, prompt: String) async throws -> String {
            let session = LanguageModelSession(instructions: system)
            return try await session.respond(to: prompt).content
        }
    }
#endif

/// Every payload that leaves the device, summarized for the ledger UI.
struct PrivacyLedgerEntry: Codable {
    let date: Date
    let backend: String
    let task: String
    let payloadSummary: String  // first ~100 chars, no full history ever sent
}
