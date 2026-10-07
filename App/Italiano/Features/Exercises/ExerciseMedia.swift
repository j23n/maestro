import Foundation
import LearningCore
import Observation

// Audio and speech as the exercise views use them: a pack audio ID becomes a clip (or nothing, before M5.1), and a
// spoken answer is one `capture` call whose live transcript the view shows. Platform-neutral; the real player and
// recogniser sit behind `AudioPlaying` and `SpeechRecognizing`.

/// Turns pack audio IDs into clips and read-along timings. The pack's `PackAudioCatalog` conforms (loaded once with
/// `PackReader.audioCatalog()`); tests and previews use `StaticAudioResolver`. A missing clip means "no speaker
/// button" (docs/06 § Shared player behaviour).
protocol AudioResolving: Sendable {
    func clip(for id: AudioID) -> AudioClip?
    func timeline(for id: AudioID) -> [TokenTiming]
    /// The audio of a whole text (`audio_text`, `source` texts, relay sources).
    func audioID(forText id: TextID) -> AudioID?
}

struct StaticAudioResolver: AudioResolving {
    var clips: [AudioID: AudioClip] = [:]
    var timelines: [AudioID: [TokenTiming]] = [:]
    var textAudio: [TextID: AudioID] = [:]

    func clip(for id: AudioID) -> AudioClip? { clips[id] }
    func timeline(for id: AudioID) -> [TokenTiming] { timelines[id] ?? [] }
    func audioID(forText id: TextID) -> AudioID? { textAudio[id] }
}

/// The exercise-level audio controller: which clip is playing, and how often each was played (the `plays` cap in
/// checks counts presses, docs/06 § Building-block formats).
@MainActor
@Observable
final class ExerciseAudio {
    let player: any AudioPlaying
    @ObservationIgnored private let resolver: any AudioResolving
    private(set) var current: AudioID?
    private(set) var playCounts: [AudioID: Int] = [:]

    init(player: any AudioPlaying, resolver: any AudioResolving) {
        self.player = player
        self.resolver = resolver
    }

    func canPlay(_ id: AudioID?) -> Bool { id.flatMap { resolver.clip(for: $0) } != nil }

    func audioID(forText id: TextID?) -> AudioID? { id.flatMap { resolver.audioID(forText: $0) } }

    func isPlaying(_ id: AudioID?) -> Bool { id != nil && current == id && player.isPlaying }

    func plays(of id: AudioID?) -> Int { id.map { playCounts[$0] ?? 0 } ?? 0 }

    /// Plays the clip from the start; returns false when there is nothing to play.
    @discardableResult
    func play(_ id: AudioID?, rate: Double = 1, context: AudioContext = .exercise) -> Bool {
        guard let id, let clip = resolver.clip(for: id) else { return false }
        current = id
        playCounts[id, default: 0] += 1
        player.play(clip, timeline: resolver.timeline(for: id), rate: rate, context: context)
        return true
    }

    /// The speaker button: stops the clip if it is the one playing, else plays it.
    func toggle(_ id: AudioID?, rate: Double = 1, context: AudioContext = .exercise) {
        if isPlaying(id) { stop() } else { play(id, rate: rate, context: context) }
    }

    func stop() {
        player.stop()
        current = nil
    }
}

/// One spoken answer at a time: idle → listening (live transcript) → finished or failed.
@MainActor
@Observable
final class SpeechCapture {
    enum State: Sendable, Equatable {
        case idle
        case listening(live: String)
        case finished(SpeechResult)
        case failed(SpeechError)
    }

    private(set) var state: State = .idle
    @ObservationIgnored private let recognizer: any SpeechRecognizing

    init(recognizer: any SpeechRecognizing) { self.recognizer = recognizer }

    var isListening: Bool { if case .listening = state { true } else { false } }

    var liveTranscript: String {
        switch state {
        case .listening(let live): live
        case .finished(let r): r.transcript
        default: ""
        }
    }

    /// The learner-facing line for a failure (docs/07 § Copy); nil otherwise.
    var failureMessage: String? {
        guard case .failed(let e) = state else { return nil }
        switch e {
        case .nothingHeard: return "I didn't hear anything. Try again, a little closer to the mic."
        case .unavailable(.denied): return "Italiano can't use the microphone. You can allow it in Settings."
        case .unavailable: return "Speaking isn't available on this device right now."
        case .cancelled: return nil
        case .failed: return "Something went wrong with listening. Try again."
        }
    }

    /// Records and transcribes one answer; nil when nothing usable came back (the state says why). The expected
    /// answers go to the recogniser as contextual strings, capped at 100 (docs/09).
    func capture(expected: [String], recordingURL: URL? = nil) async -> SpeechResult? {
        guard !isListening else { return nil }
        state = .listening(live: "")
        do {
            let result = try await recognizer.recognize(
                expected: Array(expected.prefix(100)),
                live: { [weak self] text in
                    guard let self, self.isListening else { return }
                    self.state = .listening(live: text)
                },
                recordingURL: recordingURL)
            state = .finished(result)
            return result
        } catch let e as SpeechError {
            state = e == .cancelled ? .idle : .failed(e)
            return nil
        } catch {
            state = .failed(.failed(String(describing: error)))
            return nil
        }
    }

    /// The learner tapped stop: the recogniser finishes with what it heard so far.
    func stop() { recognizer.stop() }

    func reset() { state = .idle }
}
