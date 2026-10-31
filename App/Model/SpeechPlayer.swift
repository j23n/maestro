import AVFoundation
import Foundation
import Observation

/// One stretch of text to speak, with an optional speaker for dialogue (two voices).
struct SpeechSegment: Hashable {
    let id: String          // sentence ID
    let text: String
    let speaker: String?
}

/// On-device text to speech with it-IT voices (HANDOFF.md 3.6): sentence by sentence, with the
/// word being spoken reported for highlighting.
@MainActor @Observable final class SpeechPlayer: NSObject, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()

    private(set) var segments: [SpeechSegment] = []
    private(set) var index: Int = 0
    private(set) var isPlaying = false
    /// UTF-16 range of the word being spoken, within the current segment's text.
    private(set) var wordRange: NSRange?
    var rate: Double = 0.9          // 0.6x to 1x of the normal speaking rate
    var repeatEach = false
    private var repeated = false
    private var current: ObjectIdentifier?
    private var oneShot = false

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    var currentSegment: SpeechSegment? { segments.indices.contains(index) ? segments[index] : nil }

    // MARK: Voices

    static var italianVoices: [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices().filter { $0.language == "it-IT" }
    }

    /// The best installed it-IT voice: premium, then enhanced, then the default.
    static var bestVoice: AVSpeechSynthesisVoice? {
        italianVoices.max { $0.quality.rawValue < $1.quality.rawValue } ?? AVSpeechSynthesisVoice(language: "it-IT")
    }

    static var hasEnhancedVoice: Bool {
        italianVoices.contains { $0.quality == .enhanced || $0.quality == .premium }
    }

    /// A second voice for the other speaker in a dialogue, if one is installed.
    static func voice(forSpeaker speaker: String?, in speakers: [String]) -> AVSpeechSynthesisVoice? {
        guard let speaker, let position = speakers.firstIndex(of: speaker), position % 2 == 1 else { return bestVoice }
        let best = bestVoice
        let others = italianVoices.filter { $0.identifier != best?.identifier }
            .sorted { $0.quality.rawValue > $1.quality.rawValue }
        return others.first ?? best
    }

    // MARK: Playback

    /// Speaks a word or phrase once, interrupting whatever is playing.
    func say(_ text: String) {
        stop()
        oneShot = true
        speak(text, voice: Self.bestVoice)
    }

    func load(_ segments: [SpeechSegment], startAt: Int = 0) {
        stop()
        self.segments = segments
        index = min(max(0, startAt), max(0, segments.count - 1))
    }

    func play() {
        guard let segment = currentSegment else { return }
        oneShot = false
        isPlaying = true
        repeated = false
        activateAudioSession()
        var speakers: [String] = []
        for case let speaker? in segments.map(\.speaker) where !speakers.contains(speaker) { speakers.append(speaker) }
        speak(segment.text, voice: Self.voice(forSpeaker: segment.speaker, in: speakers))
    }

    func pause() {
        isPlaying = false
        current = nil
        synthesizer.stopSpeaking(at: .immediate)
        wordRange = nil
    }

    func toggle() {
        isPlaying ? pause() : play()
    }

    func stop() {
        pause()
        oneShot = false
    }

    func next() {
        guard index + 1 < segments.count else { return }
        let wasPlaying = isPlaying
        pause()
        index += 1
        if wasPlaying { play() }
    }

    func previous() {
        guard index > 0 else { return }
        let wasPlaying = isPlaying
        pause()
        index -= 1
        if wasPlaying { play() }
    }

    func jump(to i: Int) {
        guard segments.indices.contains(i) else { return }
        let wasPlaying = isPlaying
        pause()
        index = i
        if wasPlaying { play() }
    }

    private func speak(_ text: String, voice: AVSpeechSynthesisVoice?) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = voice
        let normal = Double(AVSpeechUtteranceDefaultSpeechRate)
        utterance.rate = Float(normal * min(max(rate, 0.5), 1.0))
        utterance.postUtteranceDelay = oneShot ? 0 : 0.25
        current = ObjectIdentifier(utterance)
        synthesizer.speak(utterance)
    }

    private func activateAudioSession() {
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio)
        try? session.setActive(true)
        #endif
    }

    private func finished(_ id: ObjectIdentifier) {
        guard id == current else { return }
        wordRange = nil
        if oneShot {
            oneShot = false
            return
        }
        guard isPlaying else { return }
        if repeatEach && !repeated {
            repeated = true
            if let segment = currentSegment { speak(segment.text, voice: Self.bestVoice) }
            return
        }
        if index + 1 < segments.count {
            index += 1
            play()
        } else {
            isPlaying = false
        }
    }

    // MARK: AVSpeechSynthesizerDelegate

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, willSpeakRangeOfSpeechString characterRange: NSRange,
                                       utterance: AVSpeechUtterance) {
        let id = ObjectIdentifier(utterance)
        Task { @MainActor in
            if id == self.current { self.wordRange = characterRange }
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        let id = ObjectIdentifier(utterance)
        Task { @MainActor in self.finished(id) }
    }
}
