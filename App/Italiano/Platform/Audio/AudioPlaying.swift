import Foundation
import LearningCore
import Observation

// Playback abstraction (docs/02 § App, docs/09 § Playback). The real player wraps AVPlayer (AVAudioPlayback.swift);
// tests, previews and the Simulator without audio use `FakeAudioPlayer`. Everything here is platform-neutral.

/// One token's place in the audio, from `tokens.start_ms/end_ms` (media time, independent of the rate).
struct TokenTiming: Sendable, Equatable {
    let line: Int
    let index: Int
    let startMs: Int
    let endMs: Int
}

struct TokenPosition: Sendable, Hashable {
    let line: Int
    let index: Int
}

/// What to play: a whole file or a slice of it (a line, or a word padded 40 ms each side).
struct AudioClip: Sendable, Equatable {
    let audioID: String
    let fileURL: URL
    var startMs: Int?
    var endMs: Int?
    var textID: String?

    /// docs/09 § Segments: a single word is its token slice padded 40 ms on each side.
    static func word(_ t: TokenTiming, audioID: String, fileURL: URL, textID: String?) -> AudioClip {
        AudioClip(audioID: audioID, fileURL: fileURL, startMs: max(0, t.startMs - 40), endMs: t.endMs + 40,
                  textID: textID)
    }
}

/// Written as an `audioPlayed` event when playback stops or ends; `playedMs` is wall time spent playing.
struct PlaybackReport: Sendable, Equatable {
    let audioID: String
    let textID: String?
    let rate: Double
    let playedMs: Int
    let context: AudioContext
}

enum PlaybackRate {
    /// docs/09: 0.75 / 0.8 / 1.0 / 1.15 / 1.25 (0.75 is Play slower, 1.15 fluency replay).
    static let all: [Double] = [0.75, 0.8, 1.0, 1.15, 1.25]
    static let storyChoices: [Double] = [0.8, 1.0]
    static let slower = 0.75
    static let fluency = 1.15
}

/// Media time → token, by binary search over the start times (docs/09 § Read-along).
enum ReadAlong {
    /// The last token whose start is ≤ `ms`, or nil before the first token. `timings` must be sorted by start.
    static func token(atMs ms: Int, in timings: [TokenTiming]) -> TokenPosition? {
        var lo = 0
        var hi = timings.count - 1
        var found: Int?
        while lo <= hi {
            let mid = (lo + hi) / 2
            if timings[mid].startMs <= ms {
                found = mid
                lo = mid + 1
            } else {
                hi = mid - 1
            }
        }
        guard let i = found else { return nil }
        return TokenPosition(line: timings[i].line, index: timings[i].index)
    }

    /// The line that contains `ms`, for "tapping a line plays from that line" and line highlighting.
    static func lineStart(_ line: Int, in timings: [TokenTiming]) -> Int? {
        timings.first { $0.line == line }?.startMs
    }
}

@MainActor
protocol AudioPlaying: AnyObject, Observable {
    var isPlaying: Bool { get }
    var positionMs: Int { get }
    var durationMs: Int { get }
    var rate: Double { get }
    /// The highlighted token while playing (read-along); nil when stopped.
    var currentToken: TokenPosition? { get }
    /// Called when playback stops or reaches the end, for the `audioPlayed` event.
    var onStop: (@MainActor (PlaybackReport) -> Void)? { get set }

    func play(_ clip: AudioClip, timeline: [TokenTiming], rate: Double, context: AudioContext)
    func pause()
    func resume()
    func seek(toMs ms: Int)
    func setRate(_ rate: Double)
    func stop()
}

/// A scripted timeline for tests, previews and the Simulator: time moves only when `advance(byMs:)` is called
/// (wall time); media time advances by wall time × rate, exactly as AVPlayer does.
@MainActor
@Observable
final class FakeAudioPlayer: AudioPlaying {
    private(set) var isPlaying = false
    private(set) var positionMs = 0
    private(set) var durationMs = 0
    private(set) var rate = 1.0
    private(set) var currentToken: TokenPosition?
    private(set) var played: [AudioClip] = []
    var onStop: (@MainActor (PlaybackReport) -> Void)?

    private var clip: AudioClip?
    private var timeline: [TokenTiming] = []
    private var context: AudioContext = .item
    private var wallMs = 0

    /// Duration used when the clip has no end (a whole file).
    var defaultDurationMs = 5_000

    init() {}

    func play(_ clip: AudioClip, timeline: [TokenTiming], rate: Double, context: AudioContext) {
        if isPlaying { stop() }
        self.clip = clip
        self.timeline = timeline.sorted { $0.startMs < $1.startMs }
        self.context = context
        self.rate = rate
        positionMs = clip.startMs ?? 0
        durationMs = clip.endMs ?? defaultDurationMs
        wallMs = 0
        isPlaying = true
        played.append(clip)
        updateToken()
    }

    func pause() { isPlaying = false }

    func resume() { if clip != nil { isPlaying = true } }

    func seek(toMs ms: Int) {
        positionMs = min(max(ms, clip?.startMs ?? 0), durationMs)
        updateToken()
    }

    func setRate(_ rate: Double) { self.rate = rate }

    func stop() {
        guard let clip else { return }
        isPlaying = false
        currentToken = nil
        onStop?(PlaybackReport(audioID: clip.audioID, textID: clip.textID, rate: rate, playedMs: wallMs,
                               context: context))
        self.clip = nil
    }

    /// Move wall time forward; stops (and reports) at the clip's end.
    func advance(byMs ms: Int) {
        guard isPlaying else { return }
        wallMs += ms
        positionMs += Int((Double(ms) * rate).rounded())
        if positionMs >= durationMs {
            positionMs = durationMs
            stop()
            return
        }
        updateToken()
    }

    private func updateToken() {
        currentToken = isPlaying ? ReadAlong.token(atMs: positionMs, in: timeline) : nil
    }
}
