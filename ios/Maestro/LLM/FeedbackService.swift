// ⚠️ UNTESTED SCAFFOLD.
//
// Feedback is queued, not requested. A submission goes into the core's
// pending-feedback queue immediately and is answered whenever a backend is
// both available and allowed — which may be never, and that has to be fine.
// The deterministic layer (alignment scores, rubric checks, pre-authored
// explanations) is what the learner is owed; this is the upgrade.

import Foundation

/// A parsed feedback response. All three tasks return an object shaped
/// like this; fields absent from a given task stay empty.
struct FeedbackResponse: Codable {
    struct Mistake: Codable {
        let tag: String?
        let quote: String?
        let correction: String?
        let explanation: String?
    }

    var errors: [Mistake] = []
    var modelAnswer: String?
    var strengths: String?
    var explanation: String?
    var contrastExample: String?
    var ruleReminder: String?
    /// speaking_feedback: did they actually say the target?
    var addressedPrompt: Bool?

    enum CodingKeys: String, CodingKey {
        case errors, strengths, explanation
        case modelAnswer = "model_answer"
        case contrastExample = "contrast_example"
        case ruleReminder = "rule_reminder"
        case addressedPrompt = "addressed_prompt"
    }
}

enum FeedbackState: Equatable {
    case idle
    case queued(String)     // why it hasn't run
    case running
    case done
    case failed(String)
}

/// Why no backend could run a task — carried as the `backend(for:)` failure.
struct NoBackend: Error { let reason: String }

@Observable
final class FeedbackService {
    private let bridge: CoreBridge
    private let gates: Gates
    private let prompts: PromptLibrary?
    private let promptError: String?
    private let backends: [LLMBackend]

    var state: FeedbackState = .idle
    var response: FeedbackResponse?
    /// Everything that left the device this session, for the ledger.
    private(set) var ledger: [PrivacyLedgerEntry] = []

    init(bridge: CoreBridge, apiKey: String = "") {
        self.bridge = bridge
        self.gates = Gates.load()
        var library: PromptLibrary?
        var error: String?
        do { library = try PromptLibrary() } catch let loadError { error = "\(loadError)" }
        self.prompts = library
        self.promptError = error

        var available: [LLMBackend] = []
        #if canImport(FoundationModels)
            available.append(AppleFMBackend())
        #endif
        if !apiKey.isEmpty { available.append(AnthropicBackend(apiKey: apiKey)) }
        self.backends = available
    }

    /// The backend that may run this task, and why not if none.
    /// On-device is preferred: it's free and nothing leaves the device.
    func backend(for task: String) -> Result<LLMBackend, NoBackend> {
        guard !backends.isEmpty else {
            return .failure(NoBackend(reason: "no feedback backend configured"))
        }
        var reasons: [String] = []
        for backend in backends {
            guard gates.allows(task: task, backend: backend.name) else {
                reasons.append("\(backend.name): \(gates.reason(task: task, backend: backend.name))")
                continue
            }
            if let why = backend.unavailableReason {
                reasons.append("\(backend.name): \(why)")
                continue
            }
            return .success(backend)
        }
        return .failure(NoBackend(reason: reasons.joined(separator: "; ")))
    }

    /// Queue a submission and try to answer it now. Queuing always
    /// succeeds; answering is best-effort.
    @discardableResult
    func request(
        kind: String, itemId: String, submission: String, variables: [String: String]
    ) async -> FeedbackState {
        do {
            _ = try bridge.enqueueFeedbackJob(
                kind: kind, itemId: itemId, submission: submission,
                context: variables)
        } catch {
            state = .failed("Couldn't queue this for feedback: \(error)")
            return state
        }
        return await run(kind: kind, itemId: itemId, variables: variables)
    }

    private func run(
        kind: String, itemId: String, variables: [String: String]
    ) async -> FeedbackState {
        if let promptError {
            state = .failed(promptError)
            return state
        }
        guard let prompts else {
            state = .failed("prompts unavailable")
            return state
        }
        let chosen: LLMBackend
        switch backend(for: kind) {
        case .success(let backend):
            chosen = backend
        case .failure(let why):
            // Not an error: the queue holds it, and the deterministic
            // feedback the learner already saw stands on its own.
            state = .queued(why.reason)
            return state
        }

        state = .running
        do {
            let (system, prompt) = try prompts.render(task: kind, variables: variables)
            let raw = try await chosen.complete(system: system, prompt: prompt)
            let parsed = try Self.parse(raw)
            response = parsed
            if chosen.name != "apple_fm" {
                ledger.append(
                    PrivacyLedgerEntry(
                        date: Date(), backend: chosen.name, task: kind,
                        payloadSummary: String(prompt.prefix(100))))
            }
            state = .done
        } catch {
            state = .failed("\(error)")
        }
        return state
    }

    /// Models wrap JSON in prose or fences often enough that the harness
    /// tolerates it; the app has to tolerate exactly the same thing, or the
    /// scorecard stops describing what ships.
    static func parse(_ raw: String) throws -> FeedbackResponse {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if let start = text.firstIndex(of: "{"), let end = text.lastIndex(of: "}") {
            text = String(text[start ... end])
        }
        return try JSONDecoder().decode(FeedbackResponse.self, from: Data(text.utf8))
    }
}
