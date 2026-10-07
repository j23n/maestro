import Foundation
import Observation

// Speech recognition abstraction (docs/09 § Speech recognition). The real recogniser uses SpeechAnalyzer +
// SpeechTranscriber (it-IT) with DictationTranscriber as the fallback (SpeechAnalyzerRecognizer.swift). The
// Simulator can't run SpeechTranscriber, so tests and previews use `FakeSpeechRecognizer`; debug builds offer
// "Type to simulate speech". There is no pronunciation scoring (ADR-08).

enum SpeechAvailability: Sendable, Equatable {
    case available
    /// Italian is supported but its model isn't installed yet: show the download UI.
    case needsDownload
    /// Neither SpeechTranscriber nor DictationTranscriber supports it-IT here: speaking UI is hidden.
    case unsupported
    /// The learner denied microphone access.
    case denied
    /// `speech.enabled` is off on this device.
    case disabledInSettings

    var canSpeak: Bool { self == .available }
}

/// What the grader gets (`TranscriptMatcher` in LearningCore): the best transcript and its alternatives.
struct SpeechResult: Sendable, Equatable {
    let transcript: String
    let alternatives: [String]
    let confidence: Double?

    var allTranscripts: [String] { [transcript] + alternatives.filter { $0 != transcript } }
}

enum SpeechError: Error, Equatable {
    case unavailable(SpeechAvailability)
    case cancelled
    case nothingHeard
    case failed(String)
}

/// docs/09 § Transcription: stop after 1.2 s of silence after speech, at 10 s, or when the learner taps stop.
enum RecordingLimits {
    static let silenceAfterSpeechSeconds = 1.2
    static let maximumSeconds = 10.0
}

@MainActor
protocol SpeechRecognizing: AnyObject {
    func availability() async -> SpeechAvailability
    /// Downloads the it-IT model; reports progress 0…1. A no-op when nothing needs downloading.
    func downloadAssets(progress: @escaping @MainActor (Double) -> Void) async throws
    /// Records and transcribes one answer. `expected` may be passed to the fallback transcriber as contextual
    /// strings (≤ 100). `live` receives the volatile transcript while the learner speaks. `recordingURL`, when
    /// set, keeps an m4a of the answer (final-check speaking items always record, docs/09).
    func recognize(expected: [String], live: @escaping @MainActor (String) -> Void, recordingURL: URL?) async throws
        -> SpeechResult
    /// Stops the current recording early (the learner tapped stop).
    func stop()
}

/// Scripted transcripts for tests, previews, the Simulator and the Debug menu's "Type to simulate speech".
@MainActor
@Observable
final class FakeSpeechRecognizer: SpeechRecognizing {
    var currentAvailability: SpeechAvailability
    /// Results returned by successive `recognize` calls; when empty, `typed` is used, else `nothingHeard`.
    var scripted: [SpeechResult]
    /// The Debug menu's text field: what the learner "said".
    var typed: String?
    private(set) var recognizeCalls: [[String]] = []
    private(set) var downloads = 0

    init(availability: SpeechAvailability = .available, scripted: [SpeechResult] = []) {
        currentAvailability = availability
        self.scripted = scripted
    }

    func availability() async -> SpeechAvailability { currentAvailability }

    func downloadAssets(progress: @escaping @MainActor (Double) -> Void) async throws {
        downloads += 1
        progress(0.5)
        progress(1)
        if currentAvailability == .needsDownload { currentAvailability = .available }
    }

    func recognize(expected: [String], live: @escaping @MainActor (String) -> Void, recordingURL: URL?) async throws
        -> SpeechResult
    {
        recognizeCalls.append(expected)
        guard currentAvailability.canSpeak else { throw SpeechError.unavailable(currentAvailability) }
        if !scripted.isEmpty {
            let r = scripted.removeFirst()
            live(r.transcript)
            return r
        }
        if let typed, !typed.isEmpty {
            live(typed)
            return SpeechResult(transcript: typed, alternatives: [], confidence: nil)
        }
        throw SpeechError.nothingHeard
    }

    func stop() {}
}
