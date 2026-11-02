/// Who reads which lines aloud (HANDOFF.md 3.6). The narrator gets the best installed voice. Each
/// dialogue speaker gets a voice of their gender, a different one from the other speakers while enough
/// are installed. Two speakers who must share a voice are set apart by pitch.
///
/// The casting knows nothing about languages: the caller passes the voices installed for the text's
/// language.
public enum VoiceCasting {
    /// An installed voice, as the speech synthesizer describes it.
    public struct Voice: Sendable, Hashable {
        public let id: String
        public let gender: SpeakerGender?
        /// Higher is better: default, then enhanced, then premium.
        public let quality: Int

        public init(id: String, gender: SpeakerGender?, quality: Int) {
            self.id = id
            self.gender = gender
            self.quality = quality
        }
    }

    public struct Speaker: Sendable, Hashable {
        public let name: String
        public let gender: SpeakerGender?

        public init(name: String, gender: SpeakerGender?) {
            self.name = name
            self.gender = gender
        }
    }

    /// The voice that reads a speaker's lines.
    public struct Part: Sendable, Hashable {
        public let voiceID: String
        /// The pitch multiplier: 1 for the first speaker on a voice, higher or lower for the next ones.
        public let pitch: Float
    }

    /// Pitch for the first, second and third speaker who share a voice.
    static let pitches: [Float] = [1, 1.12, 0.9]

    /// Voices from best to worst, ties in identifier order so that every device casts the same way.
    public static func ranked(_ voices: [Voice]) -> [Voice] {
        voices.sorted { ($0.quality, $1.id) > ($1.quality, $0.id) }
    }

    /// The narrator's voice: the best installed.
    public static func narrator(_ voices: [Voice]) -> Voice? {
        ranked(voices).first
    }

    /// A part for each speaker, keyed by name, given in order of first line. A speaker without a
    /// gender, or whose gender has no installed voice, gets the least used voice of any gender.
    public static func cast(_ speakers: [Speaker], voices: [Voice]) -> [String: Part] {
        let ranked = ranked(voices)
        var uses: [String: Int] = [:]
        var parts: [String: Part] = [:]
        for speaker in speakers where parts[speaker.name] == nil {
            let matching = ranked.filter { $0.gender != nil && $0.gender == speaker.gender }
            let pool = matching.isEmpty ? ranked : matching
            guard let fewest = pool.map({ uses[$0.id, default: 0] }).min(),
                  let voice = pool.first(where: { uses[$0.id, default: 0] == fewest }) else { continue }
            uses[voice.id] = fewest + 1
            parts[speaker.name] = Part(voiceID: voice.id, pitch: pitches[fewest % pitches.count])
        }
        return parts
    }
}
