// ⚠️ UNTESTED SCAFFOLD — the FoundationModels calls were written against
// Apple's iOS 26 documentation and have never been compiled.
//
// The optional tutor layer. Two rules hold it in place:
//
//  1. Every backend is measured before it is trusted. `gates_resolved.json`
//     comes from the eval harness, and an on-device backend runs only if
//     its scorecard says it may. Wiring Apple FM in does NOT turn it on:
//     with no scorecard, the gate is closed and stays closed.
//  2. The prompts come from the bundle, not from Swift string literals —
//     the same file the harness scored (see PromptLibrary).

import Foundation

struct LLMRequest {
    let task: String  // writing_feedback | speaking_feedback | mistake_explanation
    let variables: [String: String]
}

protocol LLMBackend {
    var name: String { get }
    /// Why this backend can't run right now, or nil if it can.
    var unavailableReason: String? { get }
    func complete(system: String, prompt: String) async throws -> String
}

/// Gates: {task: {backend: {enabled, reason}}} — produced by
/// `python -m evals.harness.run --resolve-gates`, bundled at build time.
struct Gates: Codable {
    struct Verdict: Codable {
        let enabled: Bool
        let reason: String
    }

    let raw: [String: [String: Verdict]]

    static func load(bundle: Bundle = .main) -> Gates {
        guard let url = bundle.url(forResource: "gates_resolved", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let raw = try? JSONDecoder().decode([String: [String: Verdict]].self, from: data)
        else { return Gates(raw: [:]) }
        return Gates(raw: raw)
    }

    /// Cloud backends are the quality reference and are always allowed —
    /// the learner opted in by supplying a key. On-device backends are
    /// gated on measurement.
    func allows(task: String, backend: String) -> Bool {
        backend == "anthropic" || raw[task]?[backend]?.enabled == true
    }

    /// Why a task is gated off, in words worth showing a user.
    func reason(task: String, backend: String) -> String {
        raw[task]?[backend]?.reason ?? "no scorecard for \(task)"
    }
}

#if canImport(FoundationModels)
    import FoundationModels

    /// The on-device tier. Availability is Apple's answer (model present,
    /// device capable, not in a restricted state); the gate is ours.
    final class AppleFMBackend: LLMBackend {
        let name = "apple_fm"

        var unavailableReason: String? {
            switch SystemLanguageModel.default.availability {
            case .available:
                return nil
            case .unavailable(.deviceNotEligible):
                return "this device doesn't support on-device models"
            case .unavailable(.appleIntelligenceNotEnabled):
                return "turn on Apple Intelligence in Settings"
            case .unavailable(.modelNotReady):
                return "the on-device model is still downloading"
            case .unavailable(let other):
                return "on-device model unavailable (\(other))"
            @unknown default:
                return "on-device model unavailable"
            }
        }

        func complete(system: String, prompt: String) async throws -> String {
            let session = LanguageModelSession(instructions: system)
            return try await session.respond(to: prompt).content
        }
    }
#endif

/// The cloud reference tier. Off unless the learner supplies a key.
final class AnthropicBackend: LLMBackend {
    let name = "anthropic"
    private let apiKey: String

    init(apiKey: String) { self.apiKey = apiKey }

    var unavailableReason: String? { apiKey.isEmpty ? "no API key set" : nil }

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

/// Every payload that leaves the device, summarized for the ledger UI.
/// On-device work never appears here — nothing left.
struct PrivacyLedgerEntry: Codable {
    let date: Date
    let backend: String
    let task: String
    let payloadSummary: String
}
