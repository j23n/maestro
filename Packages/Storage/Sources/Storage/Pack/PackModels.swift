import Foundation
import LearningCore

// Value types for the rows of the content pack (schemas/content-pack.sql, docs/03 § The compiled content pack).
// JSON columns arrive decoded into LearningCore's payload types (M2.1). Everything is a Sendable value, so query
// results cross from the reader's queue to the main actor freely.

// MARK: - Course structure

/// A row of `units`.
public struct PackUnit: Sendable, Hashable, Identifiable {
    public let id: UnitID
    public let ord: Int
    public let titleIt: String
    public let titleEn: String
    public let episodeEn: String
    public let estMinutes: Int
    /// `final` is the final review unit `u99`.
    public let kind: UnitKind
}

/// A row of `can_dos`.
public struct PackCanDo: Sendable, Hashable, Identifiable {
    public let id: CanDoID
    public let unitId: UnitID
    public let ord: Int
    public let textEn: String
    public let cefrScale: String?
    /// A stretch can-do (beyond the unit's core).
    public let isStretch: Bool
}

/// A row of `lessons`.
public struct PackLesson: Sendable, Hashable, Identifiable {
    public let id: LessonID
    public let unitId: UnitID
    public let ord: Int
    public let titleIt: String
    public let titleEn: String
    public let estMinutes: Int
}

/// A row of `steps` with its decoded payload. Course order is `(units.ord, steps.ord)`.
public struct PackStep: Sendable, Hashable, Identifiable {
    public let id: StepID
    public let unitId: UnitID
    /// Nil for unit-level steps (opener, task steps, check, fluency).
    public let lessonId: LessonID?
    /// Order within the unit.
    public let ord: Int
    public let kind: StepKind
    public let titleEn: String?
    public let payload: StepPayload
    public let estSeconds: Int
    public let strand: Strand
    /// Unapproved content in a dev pack (the Debug overlay's draft markers).
    public let isDraft: Bool

    /// The step's exercises in presentation order (a practice mix is shuffled with the step ID as seed).
    public var exerciseOrder: [ExerciseID] { payload.exerciseOrder(stepID: id) }

    /// The texts the step shows (story, listening, reading, fluency).
    public var textIds: [TextID] { Self.textIds(of: payload) }

    /// The texts a step payload names.
    static func textIds(of payload: StepPayload) -> [TextID] {
        switch payload {
        case .story(let t, _), .listening(let t, _, _), .reading(let t, _): [t]
        case .fluency(let texts, _): texts
        default: []
        }
    }
}

/// A unit with everything the Course (Indice), Unit overview and opener screens show.
public struct PackUnitOutline: Sendable, Hashable, Identifiable {
    public let unit: PackUnit
    public let canDos: [PackCanDo]
    public let lessons: [PackLesson]
    /// Every step of the unit in order, unit-level steps included.
    public let steps: [PackStep]

    public var id: UnitID { unit.id }

    /// The steps of one lesson, in order.
    public func steps(inLesson lesson: LessonID) -> [PackStep] { steps.filter { $0.lessonId == lesson } }
}

// MARK: - Exercises, notes, assessments

/// A row of `exercises`: the decoded payload plus the columns the payload doesn't carry.
public struct PackExercise: Sendable, Hashable, Identifiable {
    public let payload: ExercisePayload
    public let estSeconds: Int
    /// `source_ref`, e.g. `u02.l1.story#3`.
    public let sourceRef: String?

    public var id: ExerciseID { payload.id }
    public var format: ExerciseFormat { payload.format }
    public var role: ExerciseRole { payload.role }
}

/// A row of `grammar_notes` with its body and the grammar points it introduces (`note_items`, in order).
public struct PackNote: Sendable, Hashable, Identifiable {
    public let id: NoteID
    public let unitId: UnitID
    public let stepId: StepID
    public let titleEn: String
    public let body: NoteBody
    /// `note_items` in `ord` order; the first is the main point.
    public let grammar: [ItemID]
}

/// The two rows of `assessments`.
public enum PackAssessmentKind: String, Sendable, CaseIterable {
    case placement, final
}

// MARK: - Items

/// A row of `items` with its `item_skills` and `item_requires`.
public struct PackItem: Sendable, Hashable, Identifiable {
    public let id: ItemID
    public let kind: ItemKind
    /// Lemma, chunk text, grammar title or sound label.
    public let it: String
    /// Nouns: `un cornetto` (generated answers).
    public let displayIndef: String?
    /// Nouns: `il cornetto`, `l'acqua (f)` (the display form, docs/03).
    public let displayDef: String?
    /// An answer pattern for generated recall cards, or nil for the default (docs/05 § Review session builder).
    public let recallAnswer: String?
    public let glossEn: String
    public let altGlossesEn: [String]
    public let noteEn: String?
    public let pos: String?
    public let gender: Gender?
    public let plural: String?
    public let unitId: UnitID
    /// Where it is introduced.
    public let lessonId: LessonID?
    /// `topic:` IDs.
    public let topics: [String]
    public let audioId: AudioID?
    /// Bit 1 cognate, bit 2 false friend.
    public let flags: Int
    /// `item_skills`: status and whether review cards are scheduled (docs/05 § Skills and what gets scheduled).
    public let skills: [Skill: ContentIndex.SkillInfo]
    /// `item_requires`, sorted.
    public let requires: [ItemID]

    public static let flagCognate = 1
    public static let flagFalseFriend = 2

    public var isCognate: Bool { flags & Self.flagCognate != 0 }
    public var isFalseFriend: Bool { flags & Self.flagFalseFriend != 0 }

    /// What cards show: the display form for nouns, else `it`.
    public var display: String { displayDef ?? it }

    /// The gloss up to the first `;` (match pairs, generated recall prompts; docs/06 §1).
    public var shortGloss: String {
        let head = glossEn.split(separator: ";", maxSplits: 1, omittingEmptySubsequences: false).first
        return head.map { $0.trimmingCharacters(in: .whitespaces) } ?? glossEn
    }

    /// The skills that get review cards, in skill order.
    public var scheduledSkills: [Skill] { skills.filter(\.value.scheduled).map(\.key).sorted() }
}

/// A row of `forms`: a surface form that occurs in course content.
public struct PackForm: Sendable, Hashable {
    /// Normalised, lowercase.
    public let form: String
    public let itemId: ItemID
    /// Morph-it! features, or empty.
    public let morph: String
}

// MARK: - Texts

/// `texts.kind`.
public enum PackTextKind: String, Sendable, Codable, CaseIterable {
    case story, dialogue, announcement, phone, message
    case realWorld = "real_world"
    case model
}

/// Where one token sits in its text's audio (`tokens.start_ms/end_ms`, media time). `line` is the line number
/// (`text_lines.ord`, 1-based as in `<textId>#n`); `index` is the token's position in that line's
/// `text.tokens` (0-based), which is what the read-along highlights.
public struct PackTokenTiming: Sendable, Hashable {
    public let line: Int
    public let index: Int
    public let startMs: Int
    public let endMs: Int

    public init(line: Int, index: Int, startMs: Int, endMs: Int) {
        self.line = line
        self.index = index
        self.startMs = startMs
        self.endMs = endMs
    }
}

/// A row of `text_lines` with its tokens.
public struct PackTextLine: Sendable, Hashable {
    /// `text_lines.ord`: 1-based, as in `u02.l1.story#3`.
    public let number: Int
    /// `ch:…`, `ch:narrator` or `ch:announcer`; nil only in real-world texts.
    public let speakerId: CharacterID?
    public let addresseeId: CharacterID?
    public let register: ExerciseBody.Register?
    /// The Italian line with its tokens (`lead` is whatever precedes the first token).
    public let text: TokenizedText
    public let en: String
    public let startMs: Int?
    public let endMs: Int?
    /// Parallel to `text.tokens`: each token's timing, or nil (punctuation, or no audio yet).
    public let tokenTimings: [PackTokenTiming?]
}

/// A row of `texts` with its lines and tokens.
public struct PackText: Sendable, Hashable, Identifiable {
    public let id: TextID
    public let unitId: UnitID
    public let kind: PackTextKind
    public let titleIt: String?
    public let titleEn: String?
    /// Real-world texts only (docs/06 §4).
    public let layout: LayoutPayload?
    /// Nil in dev packs before audio is rendered: no play button.
    public let audioId: AudioID?
    public let durationMs: Int?
    public let lines: [PackTextLine]

    /// Every timed token, sorted by start: the read-along timeline (docs/09).
    public var timeline: [PackTokenTiming] {
        lines.flatMap { $0.tokenTimings.compactMap { $0 } }.sorted {
            ($0.startMs, $0.line, $0.index) < ($1.startMs, $1.line, $1.index)
        }
    }

    /// The items the text's tokens point at, in first-occurrence order (for the word panel).
    public var itemIds: [ItemID] {
        var seen = Set<ItemID>()
        var out: [ItemID] = []
        for line in lines {
            for id in line.text.tokens.compactMap(\.itemId) where seen.insert(id).inserted { out.append(id) }
        }
        return out
    }
}

// MARK: - Audio

/// A row of `audio`, with the file's location in the bundle's `Content/Audio/`.
public struct PackAudio: Sendable, Hashable, Identifiable {
    public let id: AudioID
    /// `audio.file` (`3f9c0e1a2b4d.m4a`); always use this, never a name derived from the ID (docs/09).
    public let file: String
    public let fileURL: URL
    public let durationMs: Int
    public let voice: String
    public let sha256: String

    public init(id: AudioID, file: String, fileURL: URL, durationMs: Int, voice: String, sha256: String) {
        self.id = id
        self.file = file
        self.fileURL = fileURL
        self.durationMs = durationMs
        self.voice = voice
        self.sha256 = sha256
    }
}

/// Every audio row and every text timeline, loaded once so audio lookups are synchronous dictionary reads
/// (the App's `AudioResolving` is synchronous). Previews and tests can build one by hand.
public struct PackAudioCatalog: Sendable, Hashable {
    public let audio: [AudioID: PackAudio]
    /// Read-along timelines of the texts that have audio, keyed by the text's audio ID.
    public let timelines: [AudioID: [PackTokenTiming]]
    /// `texts.audio_id`: the audio of every text that has one.
    public let textAudio: [TextID: AudioID]
    /// The text an audio file belongs to (the first by ID if several share it); nil for item and exercise audio.
    private let audioText: [AudioID: TextID]

    public init(audio: [AudioID: PackAudio], timelines: [AudioID: [PackTokenTiming]], textAudio: [TextID: AudioID]) {
        self.audio = audio
        self.timelines = timelines
        self.textAudio = textAudio
        var audioText: [AudioID: TextID] = [:]
        for (text, id) in textAudio where audioText[id].map({ text < $0 }) ?? true { audioText[id] = text }
        self.audioText = audioText
    }

    public static let empty = PackAudioCatalog(audio: [:], timelines: [:], textAudio: [:])

    public func audio(_ id: AudioID) -> PackAudio? { audio[id] }
    public func timeline(_ id: AudioID) -> [PackTokenTiming] { timelines[id] ?? [] }
    /// The audio of a whole text (`audio_text`, `source` texts, relay sources), or nil before it is rendered.
    public func audioID(forText id: TextID) -> AudioID? { textAudio[id] }
    public func textID(forAudio id: AudioID) -> TextID? { audioText[id] }
}

// MARK: - People and places

/// A row of `characters` (including `ch:narrator` and `ch:announcer`).
public struct PackCharacter: Sendable, Hashable, Identifiable {
    public let id: CharacterID
    public let name: String
    public let descriptionEn: String
}

/// A row of `countries` (onboarding's "Where do you live?", personal answer slots).
public struct PackCountry: Sendable, Hashable, Identifiable {
    /// ISO 3166-1 alpha-2, lowercase; `gb-eng`, `gb-sct`, `gb-wls`, `gb-nir` for the UK nations.
    public let id: String
    public let nameEn: String
    public let nameIt: String
    /// `negli Stati Uniti`, `in Canada`.
    public let homePhraseIt: String
    /// Accepted in answers, never shown.
    public let altHomePhrasesIt: [String]
    public let nationalityM: String
    public let nationalityF: String

    /// The grader's view of the row (`{ME.home}`, `{ME.nationality}`, `{ME.country}`).
    public var profileCountry: LearnerProfile.Country {
        LearnerProfile.Country(id: id, nameIt: nameIt, homePhrase: homePhraseIt, altHomePhrases: altHomePhrasesIt,
                               nationalityM: nationalityM, nationalityF: nationalityF)
    }
}
