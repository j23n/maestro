import AVFoundation
import Foundation
import LanguageCore
import Observation
import PackKit

/// One stretch of text to speak, with the speaker and their gender for a line of dialogue.
struct SpeechSegment: Hashable {
    let id: String          // sentence ID
    let text: String
    let speaker: String?
    var gender: SpeakerGender? = nil
}

/// On-device text to speech in the active language's voices, it-IT or de-DE (HANDOFF.md 3.6): sentence
/// by sentence, with the word being spoken reported for highlighting.
@MainActor @Observable final class SpeechPlayer: NSObject, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    /// The language whose voices read. Changing it stops playback, since what is loaded is in the old one.
    var language: Language = .it {
        didSet { if language != oldValue { stop(); segments = []; index = 0 } }
    }

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
    /// The voice for each dialogue speaker in the loaded segments.
    private var parts: [String: VoiceCasting.Part] = [:]

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    var currentSegment: SpeechSegment? { segments.indices.contains(index) ? segments[index] : nil }

    // MARK: Voices

    /// Installed voices for a language (it-IT, de-DE) that sound natural enough to read a text.
    static func voices(for language: Language) -> [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices().filter { $0.language == language.bcp47 && isReadingVoice($0) }
    }

    /// Leaves out the Eloquence voices (Eddy, Flo, Grandma…), which sound robotic, and novelty and
    /// personal voices.
    static func isReadingVoice(_ voice: AVSpeechSynthesisVoice) -> Bool {
        !voice.identifier.hasPrefix("com.apple.eloquence.")
            && voice.voiceTraits.isDisjoint(with: [.isNoveltyVoice, .isPersonalVoice])
    }

    /// The narrator's voice: the language's best installed voice, premium, then enhanced, then the default,
    /// with ties broken as `VoiceCasting` breaks them, so that a narrator who also speaks keeps one voice.
    static func bestVoice(for language: Language) -> AVSpeechSynthesisVoice? {
        VoiceCasting.narrator(voices(for: language).map { VoiceCasting.Voice($0) })
            .flatMap { AVSpeechSynthesisVoice(identifier: $0.id) } ?? AVSpeechSynthesisVoice(language: language.bcp47)
    }

    static func hasEnhancedVoice(for language: Language) -> Bool {
        voices(for: language).contains { $0.quality == .enhanced || $0.quality == .premium }
    }

    /// A voice for each dialogue speaker, matching their gender where such a voice is installed.
    static func cast(_ segments: [SpeechSegment], language: Language) -> [String: VoiceCasting.Part] {
        var speakers: [VoiceCasting.Speaker] = []
        for segment in segments {
            guard let name = segment.speaker, !speakers.contains(where: { $0.name == name }) else { continue }
            speakers.append(VoiceCasting.Speaker(name: name, gender: segment.gender))
        }
        return VoiceCasting.cast(speakers, voices: voices(for: language).map { VoiceCasting.Voice($0) })
    }

    // MARK: Playback

    /// Speaks a word or phrase once, interrupting whatever is playing.
    func say(_ text: String) {
        stop()
        oneShot = true
        speak(text, voice: Self.bestVoice(for: language))
    }

    func load(_ segments: [SpeechSegment], startAt: Int = 0) {
        stop()
        self.segments = segments
        parts = Self.cast(segments, language: language)
        index = min(max(0, startAt), max(0, segments.count - 1))
    }

    func play() {
        guard let segment = currentSegment else { return }
        oneShot = false
        isPlaying = true
        repeated = false
        activateAudioSession()
        speak(segment)
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

    /// Speaks a segment in its speaker's voice, or the narrator's.
    private func speak(_ segment: SpeechSegment) {
        if let speaker = segment.speaker, let part = parts[speaker],
           let voice = AVSpeechSynthesisVoice(identifier: part.voiceID) {
            speak(segment.text, voice: voice, pitch: part.pitch)
        } else {
            speak(segment.text, voice: Self.bestVoice(for: language))
        }
    }

    private func speak(_ text: String, voice: AVSpeechSynthesisVoice?, pitch: Float = 1) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = voice
        utterance.pitchMultiplier = pitch
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
            if let segment = currentSegment { speak(segment) }
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

extension VoiceCasting.Voice {
    init(_ voice: AVSpeechSynthesisVoice) {
        let gender: SpeakerGender? = switch voice.gender {
        case .female: .female
        case .male: .male
        default: nil
        }
        self.init(id: voice.identifier, gender: gender, quality: voice.quality.rawValue)
    }
}
