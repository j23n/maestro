import Foundation
import Observation

/// The Debug menu's "Simulate speech by typing" (docs/02, docs/09): builds with the Debug menu wrap the real
/// recogniser in this. Switched off, every call goes to the real recogniser. Switched on, speech is available and
/// each recording asks for typed text instead (`prompt`, which the player's debug overlay shows), so speaking
/// exercises can be played in the Simulator, which can't run SpeechTranscriber.
@MainActor
@Observable
final class SimulatedSpeechRecognizer: SpeechRecognizing {
    /// A recording waiting for its typed transcript.
    struct Prompt: Identifiable, Equatable, Sendable {
        let id: Int
        /// What the exercise accepts (shown as a reminder of what to type).
        let expected: [String]
    }

    @ObservationIgnored let real: any SpeechRecognizing
    /// Turning simulation off cancels a waiting prompt.
    var isSimulating = false {
        didSet { if !isSimulating { finish(with: nil) } }
    }
    private(set) var prompt: Prompt?
    @ObservationIgnored private var waiting: CheckedContinuation<String?, Never>?
    @ObservationIgnored private var nextID = 0

    init(real: any SpeechRecognizing) { self.real = real }

    func availability() async -> SpeechAvailability {
        isSimulating ? .available : await real.availability()
    }

    func downloadAssets(progress: @escaping @MainActor (Double) -> Void) async throws {
        if isSimulating {
            progress(1)
            return
        }
        try await real.downloadAssets(progress: progress)
    }

    func recognize(
        expected: [String], live: @escaping @MainActor (String) -> Void, recordingURL: URL?
    ) async throws -> SpeechResult {
        guard isSimulating else {
            return try await real.recognize(expected: expected, live: live, recordingURL: recordingURL)
        }
        finish(with: nil)  // a stale prompt never answers a new recording
        nextID += 1
        let id = nextID
        let typed = await withCheckedContinuation { continuation in
            waiting = continuation
            prompt = Prompt(id: id, expected: expected)
        }
        guard let typed else { throw SpeechError.cancelled }
        let text = typed.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { throw SpeechError.nothingHeard }
        live(text)
        return SpeechResult(transcript: text, alternatives: [], confidence: nil)
    }

    /// The overlay's "Say it": the typed text is what the learner said.
    func submit(_ text: String) { finish(with: text) }

    /// The overlay's Cancel, or the learner stopping the recording.
    func cancel() { finish(with: nil) }

    func stop() {
        if isSimulating { finish(with: nil) } else { real.stop() }
    }

    private func finish(with text: String?) {
        prompt = nil
        let continuation = waiting
        waiting = nil
        continuation?.resume(returning: text)
    }
}
