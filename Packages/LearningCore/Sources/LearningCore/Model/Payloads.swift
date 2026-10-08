import Foundation

// Pack payloads (M2.1): the JSON in steps.payload, exercises.payload, grammar_notes.body and assessments.payload,
// exactly as schemas/pack-payloads.schema.json defines it. Unknown keys are ignored; a missing non-optional key is a
// decode error (fixtures/packs/payload-examples.json and mini-payloads.json are decoded in tests on Linux).

// MARK: - Shared shapes

public enum TokenKind: String, Codable, Sendable { case word, punct, name, number, foreign }

/// One token of an Italian string, as in the pack's `tokens` table.
public struct PackToken: Codable, Sendable, Hashable {
    public let surface: String
    public let trailing: String
    public let kind: TokenKind
    public let itemId: ItemID?
    public let gloss: String?
    public let flags: Int

    public init(surface: String, trailing: String, kind: TokenKind, itemId: ItemID?, gloss: String?, flags: Int) {
        self.surface = surface
        self.trailing = trailing
        self.kind = kind
        self.itemId = itemId
        self.gloss = gloss
        self.flags = flags
    }

    public static let flagNew = 1
    public static let flagRecogniseOnly = 2
    public static let flagLessonTarget = 4

    public var isNew: Bool { flags & Self.flagNew != 0 }
    /// Words can be tapped for a gloss; names and punctuation can't (docs/06 §2).
    public var isTappable: Bool { kind == .word || kind == .foreign }
}

/// An Italian string with its tokens: `lead + Σ(surface + trailing) == text`.
public struct TokenizedText: Codable, Sendable, Hashable {
    public let text: String
    public let lead: String
    public let tokens: [PackToken]

    public init(text: String, lead: String = "", tokens: [PackToken]) {
        self.text = text
        self.lead = lead
        self.tokens = tokens
    }

    /// The text rebuilt from its tokens (equals `text` for every pack the pipeline builds).
    public var rebuilt: String { lead + tokens.map { $0.surface + $0.trailing }.joined() }
}

/// An answer pattern as authored plus its learner-independent expansions (for the answer key).
public struct PatternPayload: Codable, Sendable, Hashable {
    public let source: String
    public let expansions: [String]

    public init(source: String, expansions: [String]) {
        self.source = source
        self.expansions = expansions
    }

    public func parsed() throws(PatternError) -> AnswerPattern { try AnswerPattern(source) }
}

public struct NearPayload: Codable, Sendable, Hashable {
    /// `correctWithNote` marks an answer that is right but gets a note (a bare noun in a generated recall:
    /// "Say it with its article", docs/05 § Review session builder); authored near-misses may use it too.
    public enum Outcome: String, Codable, Sendable { case wrong, almost, correctWithNote }
    public let answer: PatternPayload
    public let outcome: Outcome
    public let hint: String?

    public func nearMiss() throws(PatternError) -> TypedAnswerGrader.NearMiss {
        let graded: AttemptOutcome =
            switch outcome {
            case .wrong: .wrong
            case .almost: .almost
            case .correctWithNote: .correctWithNote
            }
        return TypedAnswerGrader.NearMiss(try answer.parsed(), outcome: graded, hint: hint)
    }
}

public struct TargetPayload: Codable, Sendable, Hashable {
    public let itemId: ItemID
    public let skill: Skill

    public init(itemId: ItemID, skill: Skill) {
        self.itemId = itemId
        self.skill = skill
    }
}

/// `source: u02.l1.story#3` (a line) or `{text: u02.task.menu}` (a whole text).
public struct SourceRef: Codable, Sendable, Hashable {
    public let textId: TextID
    public let line: Int?
}

// MARK: - Exercises

public struct ExercisePayload: Codable, Sendable, Hashable {
    public let id: ExerciseID
    public let format: ExerciseFormat
    public let role: ExerciseRole
    public let unitId: UnitID
    public let stepId: StepID?
    public let score: Int
    public let targets: [TargetPayload]
    public let tags: [String]
    public let source: SourceRef?
    public let hint: String?
    public let rule: String?
    public let near: [NearPayload]
    public let audioAfter: Bool
    public let body: ExerciseBody

    private enum CodingKeys: String, CodingKey {
        case id, format, role, unitId, stepId, score, targets, tags, source, hint, rule, near, audioAfter
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(ExerciseID.self, forKey: .id)
        format = try c.decode(ExerciseFormat.self, forKey: .format)
        role = try c.decode(ExerciseRole.self, forKey: .role)
        unitId = try c.decode(UnitID.self, forKey: .unitId)
        stepId = try c.decodeIfPresent(StepID.self, forKey: .stepId)
        score = try c.decodeIfPresent(Int.self, forKey: .score) ?? 1
        targets = try c.decode([TargetPayload].self, forKey: .targets)
        tags = try c.decode([String].self, forKey: .tags)
        source = try c.decodeIfPresent(SourceRef.self, forKey: .source)
        hint = try c.decodeIfPresent(String.self, forKey: .hint)
        rule = try c.decodeIfPresent(String.self, forKey: .rule)
        near = try c.decodeIfPresent([NearPayload].self, forKey: .near) ?? []
        audioAfter = try c.decodeIfPresent(Bool.self, forKey: .audioAfter) ?? false
        body = try ExerciseBody(format: format, from: decoder)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(format, forKey: .format)
        try c.encode(role, forKey: .role)
        try c.encode(unitId, forKey: .unitId)
        try c.encode(stepId, forKey: .stepId)
        try c.encode(score, forKey: .score)
        try c.encode(targets, forKey: .targets)
        try c.encode(tags, forKey: .tags)
        try c.encode(source, forKey: .source)
        try c.encode(hint, forKey: .hint)
        try c.encode(rule, forKey: .rule)
        try c.encode(near, forKey: .near)
        try c.encode(audioAfter, forKey: .audioAfter)
        try body.encode(to: encoder)
    }

    /// The near misses as grader input (patterns that fail to parse are a pack bug and are skipped).
    public func nearMisses() -> [TypedAnswerGrader.NearMiss] { near.compactMap { try? $0.nearMiss() } }
}

public enum ExerciseBody: Sendable, Hashable {
    case cloze(Cloze)
    case recall(Recall)
    case sentenceBuilding(SentenceBuilding)
    case dictation(Dictation)
    case soundPair(SoundPair)
    case `repeat`(Repeat)
    case choice(Choice)
    case trueFalse(TrueFalse)
    case match(Match)
    case conversation(Conversation)
    case talk(Talk)
    case writing(Writing)
    case relay(Relay)

    init(format: ExerciseFormat, from decoder: Decoder) throws {
        switch format {
        case .cloze: self = .cloze(try Cloze(from: decoder))
        case .recall: self = .recall(try Recall(from: decoder))
        case .sentenceBuilding: self = .sentenceBuilding(try SentenceBuilding(from: decoder))
        case .dictation: self = .dictation(try Dictation(from: decoder))
        case .soundPair: self = .soundPair(try SoundPair(from: decoder))
        case .repeat: self = .repeat(try Repeat(from: decoder))
        case .choice: self = .choice(try Choice(from: decoder))
        case .trueFalse: self = .trueFalse(try TrueFalse(from: decoder))
        case .match: self = .match(try Match(from: decoder))
        case .conversation: self = .conversation(try Conversation(from: decoder))
        case .talk: self = .talk(try Talk(from: decoder))
        case .writing: self = .writing(try Writing(from: decoder))
        case .relay: self = .relay(try Relay(from: decoder))
        }
    }

    func encode(to encoder: Encoder) throws {
        switch self {
        case .cloze(let b): try b.encode(to: encoder)
        case .recall(let b): try b.encode(to: encoder)
        case .sentenceBuilding(let b): try b.encode(to: encoder)
        case .dictation(let b): try b.encode(to: encoder)
        case .soundPair(let b): try b.encode(to: encoder)
        case .repeat(let b): try b.encode(to: encoder)
        case .choice(let b): try b.encode(to: encoder)
        case .trueFalse(let b): try b.encode(to: encoder)
        case .match(let b): try b.encode(to: encoder)
        case .conversation(let b): try b.encode(to: encoder)
        case .talk(let b): try b.encode(to: encoder)
        case .writing(let b): try b.encode(to: encoder)
        case .relay(let b): try b.encode(to: encoder)
        }
    }

    public struct Cloze: Codable, Sendable, Hashable {
        public let before: TokenizedText
        public let gap: PatternPayload
        public let after: TokenizedText
        public let promptEn: String?
        public let bank: [String]?
        public let audioId: AudioID?

        /// The gap as a pattern: all focus (docs/03).
        public func gapPattern() throws(PatternError) -> AnswerPattern { try AnswerPattern.clozeGap(gap.source) }
    }

    public struct Recall: Codable, Sendable, Hashable {
        public let promptEn: String
        public let contextIt: TokenizedText?
        public let answer: PatternPayload
        public let answerAudioId: AudioID?
    }

    public struct SentenceBuilding: Codable, Sendable, Hashable {
        public let promptEn: String
        public let tiles: [String]
        public let distractors: [String]
        public let answers: [String]
        public let answerAudioId: AudioID?

        /// Tiles and distractors in the seeded order every device shows (docs/06 §8: never the answer order).
        public func shuffledTiles(exerciseID: ExerciseID) -> [String] {
            let all = tiles + distractors
            var rng = SplitMix64(seedString: exerciseID.rawValue)
            var order = all.seededShuffle(using: &rng)
            var guardCount = 0
            while answers.contains(order.joined(separator: " ")) && guardCount < 8 {
                order = all.seededShuffle(using: &rng)
                guardCount += 1
            }
            return order
        }
    }

    public struct Dictation: Codable, Sendable, Hashable {
        public let say: TokenizedText
        public let audioId: AudioID?
        public let slow: Bool
        public let plays: Int?
    }

    public struct SoundWord: Codable, Sendable, Hashable {
        public let it: String
        public let gloss: String?
        public let audioId: AudioID?
    }

    public struct SoundPair: Codable, Sendable, Hashable {
        public enum Question: String, Codable, Sendable {
            case whichWord = "which-word"
            case singleOrDouble = "single-or-double"
        }

        public enum Length: String, Codable, Sendable { case single, double }

        public let question: Question
        public let pair: [SoundWord]?
        public let play: Int?
        public let word: SoundWord?
        public let answer: Length?
        public let tipEn: String?
    }

    public struct Repeat: Codable, Sendable, Hashable {
        public let say: TokenizedText
        public let audioId: AudioID?
        public let accept: PatternPayload
    }

    public struct Option: Codable, Sendable, Hashable {
        public let text: String
        public let it: TokenizedText?
    }

    public struct Choice: Codable, Sendable, Hashable {
        public let promptIt: TokenizedText?
        public let promptAudioId: AudioID?
        public let audioTextId: TextID?
        public let plays: Int?
        public let questionEn: String
        public let options: [Option]
        public let answer: Int

        /// Option indices (into `options` as authored) in the seeded order every device shows.
        public func displayOrder(exerciseID: ExerciseID) -> [Int] {
            Array(options.indices).seededShuffle(seed: exerciseID.rawValue)
        }
    }

    public struct TrueFalse: Codable, Sendable, Hashable {
        public let statementEn: String
        public let answer: Bool
        public let audioTextId: TextID?
        public let plays: Int?
    }

    public struct MatchPair: Codable, Sendable, Hashable {
        public let left: TokenizedText
        public let right: String
        public let leftAudioId: AudioID?
    }

    public struct Match: Codable, Sendable, Hashable {
        public let pairs: [MatchPair]

        /// The right column in the seeded order every device shows (indices into `pairs`).
        public func rightOrder(exerciseID: ExerciseID) -> [Int] {
            Array(pairs.indices).seededShuffle(seed: exerciseID.rawValue + "#right")
        }

        public func leftOrder(exerciseID: ExerciseID) -> [Int] {
            Array(pairs.indices).seededShuffle(seed: exerciseID.rawValue + "#left")
        }
    }

    public struct Goal: Codable, Sendable, Hashable {
        public let id: String
        public let en: String
    }

    public enum Register: String, Codable, Sendable { case tu, lei }

    public struct Expectation: Codable, Sendable, Hashable {
        public let intent: String
        public let goal: String?
        public let accept: [PatternPayload]
        public let next: String
    }

    public struct ConversationNode: Codable, Sendable, Hashable {
        public let id: String
        public let say: TokenizedText
        public let en: String
        public let audioId: AudioID?
        public let expect: [Expectation]
        public let near: [NearPayload]
        public let help: [TokenizedText]
        public let hintEn: String?
        public let register: Register?
        public let `final`: Bool

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            id = try c.decode(String.self, forKey: .id)
            say = try c.decode(TokenizedText.self, forKey: .say)
            en = try c.decode(String.self, forKey: .en)
            audioId = try c.decodeIfPresent(AudioID.self, forKey: .audioId)
            expect = try c.decodeIfPresent([Expectation].self, forKey: .expect) ?? []
            near = try c.decodeIfPresent([NearPayload].self, forKey: .near) ?? []
            help = try c.decodeIfPresent([TokenizedText].self, forKey: .help) ?? []
            hintEn = try c.decodeIfPresent(String.self, forKey: .hintEn)
            register = try c.decodeIfPresent(Register.self, forKey: .register)
            `final` = try c.decodeIfPresent(Bool.self, forKey: .final) ?? false
        }

        private enum CodingKeys: String, CodingKey {
            case id, say, en, audioId, expect, near, help, hintEn, register, `final`
        }
    }

    public struct Conversation: Codable, Sendable, Hashable {
        public let with: CharacterID
        public let register: Register
        public let titleEn: String
        public let goals: [Goal]
        public let start: String
        public let nodes: [ConversationNode]

        public func node(_ id: String) -> ConversationNode? { nodes.first { $0.id == id } }

        /// The register in force at a node: the latest override on the path, else the conversation's.
        public func register(at nodeID: String, path: [String]) -> Register {
            for id in (path + [nodeID]).reversed() {
                if let r = node(id)?.register { return r }
            }
            return register
        }
    }

    public struct Point: Codable, Sendable, Hashable {
        public let id: String
        public let en: String
        public let accept: [PatternPayload]

        public func matcherPoint() throws(PatternError) -> ContentPointMatcher.Point {
            var patterns: [AnswerPattern] = []
            for p in accept { patterns.append(try p.parsed()) }
            return ContentPointMatcher.Point(id: id, accept: patterns)
        }
    }

    public struct Duration: Codable, Sendable, Hashable {
        public let min: Int
        public let max: Int
    }

    public struct Talk: Codable, Sendable, Hashable {
        public let promptEn: String
        public let points: [Point]
        public let pass: Int
        public let model: TokenizedText
        public let modelAudioId: AudioID?
        public let durationS: Duration
    }

    public struct FormField: Codable, Sendable, Hashable {
        public enum FieldType: String, Codable, Sendable { case text, email, number, date, phone }
        public let labelIt: TokenizedText
        public let labelEn: String
        public let type: FieldType
        public let accept: [PatternPayload]?
    }

    public struct Writing: Codable, Sendable, Hashable {
        public enum Kind: String, Codable, Sendable { case form, message, postcard, list, description }
        public let kind: Kind
        public let promptEn: String
        public let fields: [FormField]?
        public let words: Duration?
        public let points: [Point]?
        public let pass: Int?
        public let model: TokenizedText?
    }

    public struct RelayAnswer: Codable, Sendable, Hashable {
        public enum AnswerType: String, Codable, Sendable { case time, price, number, text }
        public let type: AnswerType
        public let value: JSONScalar?
        public let accept: [String]?

        /// The grader's answer, or nil when the payload is inconsistent (a pack bug).
        public var graderAnswer: EnglishAnswerGrader.Answer? {
            switch type {
            case .price: return value?.doubleValue.map { .price($0) }
            case .number: return value?.doubleValue.map { .number(Int($0.rounded())) }
            case .text: return accept.map { .text($0) }
            case .time:
                guard case .string(let s)? = value else { return nil }
                let parts = s.split(separator: ":").compactMap { Int($0) }
                return parts.count == 2 ? .time(hour: parts[0], minute: parts[1]) : nil
            }
        }
    }

    public struct Relay: Codable, Sendable, Hashable {
        public let sourceTextId: TextID?
        public let audioTextId: TextID?
        public let friendEn: String
        public let answerEn: RelayAnswer
    }
}

/// A JSON number or string (relay values).
public enum JSONScalar: Codable, Sendable, Hashable {
    case number(Double)
    case string(String)

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let d = try? c.decode(Double.self) {
            self = .number(d)
        } else {
            self = .string(try c.decode(String.self))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .number(let d): try c.encode(d)
        case .string(let s): try c.encode(s)
        }
    }

    public var doubleValue: Double? {
        switch self {
        case .number(let d): d
        case .string(let s): Double(s.replacingOccurrences(of: ",", with: "."))
        }
    }
}

// MARK: - Steps

public enum StepPayload: Codable, Sendable, Hashable {
    public struct PreviewBatch: Codable, Sendable, Hashable {
        public let itemIds: [ItemID]
        public let exerciseIds: [ExerciseID]
    }

    public struct CheckSection: Codable, Sendable, Hashable {
        public let id: String
        public let titleEn: String
        public let exerciseIds: [ExerciseID]
    }

    public struct PassRule: Codable, Sendable, Hashable {
        public let overall: Double
        public let sectionMin: Double
    }

    case opener(unitId: UnitID)
    case preview(batches: [PreviewBatch])
    case story(textId: TextID, questionIds: [ExerciseID])
    case listening(textId: TextID, plays: Int?, exerciseIds: [ExerciseID])
    case reading(textId: TextID, exerciseIds: [ExerciseID])
    case note(noteId: NoteID)
    case practice(block: [ExerciseID], mix: [ExerciseID])
    case sounds(exerciseIds: [ExerciseID])
    case single(kind: StepKind, exerciseId: ExerciseID)  // use, conversation, talk, writing, relay
    case check(checkId: String, pass: PassRule, sections: [CheckSection])
    case fluency(textIds: [TextID], rate: Double)

    private enum CodingKeys: String, CodingKey {
        case kind, unitId, batches, textId, questionIds, plays, exerciseIds, noteId, block, mix, exerciseId
        case checkId, pass, sections, textIds, rate
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let kind = try c.decode(StepKind.self, forKey: .kind)
        switch kind {
        case .opener: self = .opener(unitId: try c.decode(UnitID.self, forKey: .unitId))
        case .preview: self = .preview(batches: try c.decode([PreviewBatch].self, forKey: .batches))
        case .story:
            self = .story(textId: try c.decode(TextID.self, forKey: .textId),
                          questionIds: try c.decode([ExerciseID].self, forKey: .questionIds))
        case .listening:
            self = .listening(textId: try c.decode(TextID.self, forKey: .textId),
                              plays: try c.decodeIfPresent(Int.self, forKey: .plays),
                              exerciseIds: try c.decode([ExerciseID].self, forKey: .exerciseIds))
        case .reading:
            self = .reading(textId: try c.decode(TextID.self, forKey: .textId),
                            exerciseIds: try c.decode([ExerciseID].self, forKey: .exerciseIds))
        case .note: self = .note(noteId: try c.decode(NoteID.self, forKey: .noteId))
        case .practice:
            self = .practice(block: try c.decode([ExerciseID].self, forKey: .block),
                             mix: try c.decode([ExerciseID].self, forKey: .mix))
        case .sounds: self = .sounds(exerciseIds: try c.decode([ExerciseID].self, forKey: .exerciseIds))
        case .use, .conversation, .talk, .writing, .relay:
            self = .single(kind: kind, exerciseId: try c.decode(ExerciseID.self, forKey: .exerciseId))
        case .check:
            self = .check(checkId: try c.decode(String.self, forKey: .checkId),
                          pass: try c.decode(PassRule.self, forKey: .pass),
                          sections: try c.decode([CheckSection].self, forKey: .sections))
        case .fluency:
            self = .fluency(textIds: try c.decode([TextID].self, forKey: .textIds),
                            rate: try c.decode(Double.self, forKey: .rate))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(kind, forKey: .kind)
        switch self {
        case .opener(let u): try c.encode(u, forKey: .unitId)
        case .preview(let b): try c.encode(b, forKey: .batches)
        case .story(let t, let q):
            try c.encode(t, forKey: .textId)
            try c.encode(q, forKey: .questionIds)
        case .listening(let t, let p, let e):
            try c.encode(t, forKey: .textId)
            try c.encode(p, forKey: .plays)
            try c.encode(e, forKey: .exerciseIds)
        case .reading(let t, let e):
            try c.encode(t, forKey: .textId)
            try c.encode(e, forKey: .exerciseIds)
        case .note(let n): try c.encode(n, forKey: .noteId)
        case .practice(let b, let m):
            try c.encode(b, forKey: .block)
            try c.encode(m, forKey: .mix)
        case .sounds(let e): try c.encode(e, forKey: .exerciseIds)
        case .single(_, let e): try c.encode(e, forKey: .exerciseId)
        case .check(let id, let p, let s):
            try c.encode(id, forKey: .checkId)
            try c.encode(p, forKey: .pass)
            try c.encode(s, forKey: .sections)
        case .fluency(let t, let r):
            try c.encode(t, forKey: .textIds)
            try c.encode(r, forKey: .rate)
        }
    }

    public var kind: StepKind {
        switch self {
        case .opener: .opener
        case .preview: .preview
        case .story: .story
        case .listening: .listening
        case .reading: .reading
        case .note: .note
        case .practice: .practice
        case .sounds: .sounds
        case .single(let k, _): k
        case .check: .check
        case .fluency: .fluency
        }
    }

    /// The exercises of the step in presentation order. A practice step is its block, then its mix shuffled with
    /// SplitMix64 seeded by FNV-1a 64 of the step ID, so every device resumes at the same exercise (docs/05).
    public func exerciseOrder(stepID: StepID) -> [ExerciseID] {
        switch self {
        case .preview(let batches): batches.flatMap(\.exerciseIds)
        case .story(_, let q): q
        case .listening(_, _, let e), .reading(_, let e), .sounds(let e): e
        case .practice(let block, let mix): block + mix.seededShuffle(seed: stepID.rawValue)
        case .single(_, let e): [e]
        case .check(_, _, let sections): sections.flatMap(\.exerciseIds)
        case .opener, .note, .fluency: []
        }
    }
}

// MARK: - Grammar notes and assessments

public struct NoteBody: Codable, Sendable, Hashable {
    public struct Intro: Codable, Sendable, Hashable {
        public let mascot: String
        public let textEn: String
    }

    public struct Example: Codable, Sendable, Hashable {
        public let ref: String
        public let textId: TextID
        public let line: Int
        public let text: TokenizedText
        public let highlight: [Int]
        public let en: String
    }

    public struct Table: Codable, Sendable, Hashable {
        public let columns: [String]
        public let rows: [[String]]
    }

    public enum Block: Codable, Sendable, Hashable {
        case paragraph(String)
        case table(Table)
        case examples([Example])
        case tip(String)

        private enum CodingKeys: String, CodingKey { case p, table, examples, tip }

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            if let p = try c.decodeIfPresent(String.self, forKey: .p) {
                self = .paragraph(p)
            } else if let t = try c.decodeIfPresent(Table.self, forKey: .table) {
                self = .table(t)
            } else if let e = try c.decodeIfPresent([Example].self, forKey: .examples) {
                self = .examples(e)
            } else if let t = try c.decodeIfPresent(String.self, forKey: .tip) {
                self = .tip(t)
            } else {
                throw DecodingError.dataCorrupted(
                    .init(codingPath: decoder.codingPath, debugDescription: "a note block needs p, table, examples or tip"))
            }
        }

        public func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            switch self {
            case .paragraph(let p): try c.encode(p, forKey: .p)
            case .table(let t): try c.encode(t, forKey: .table)
            case .examples(let e): try c.encode(e, forKey: .examples)
            case .tip(let t): try c.encode(t, forKey: .tip)
            }
        }
    }

    public let noteId: NoteID
    public let titleEn: String
    public let grammar: [ItemID]
    public let intro: Intro?
    public let blocks: [Block]
}

public enum AssessmentPayload: Codable, Sendable, Hashable {
    public struct PlacementBlock: Codable, Sendable, Hashable {
        public let unitId: UnitID
        public let exerciseIds: [ExerciseID]
    }

    public struct FinalSection: Codable, Sendable, Hashable {
        public let id: String
        public let titleEn: String
        public let max: Int
        public let exerciseIds: [ExerciseID]
    }

    case placement(advanceThreshold: Int, blocks: [PlacementBlock])
    case final(indicativePassPerSection: Int, sections: [FinalSection])

    private enum CodingKeys: String, CodingKey { case id, advanceThreshold, blocks, indicativePassPerSection, sections }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        switch try c.decode(String.self, forKey: .id) {
        case "placement":
            self = .placement(advanceThreshold: try c.decode(Int.self, forKey: .advanceThreshold),
                              blocks: try c.decode([PlacementBlock].self, forKey: .blocks))
        case "final":
            self = .final(indicativePassPerSection: try c.decode(Int.self, forKey: .indicativePassPerSection),
                          sections: try c.decode([FinalSection].self, forKey: .sections))
        case let other:
            throw DecodingError.dataCorruptedError(forKey: .id, in: c, debugDescription: "unknown assessment \(other)")
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .placement(let t, let b):
            try c.encode("placement", forKey: .id)
            try c.encode(t, forKey: .advanceThreshold)
            try c.encode(b, forKey: .blocks)
        case .final(let p, let s):
            try c.encode("final", forKey: .id)
            try c.encode(p, forKey: .indicativePassPerSection)
            try c.encode(s, forKey: .sections)
        }
    }
}

public enum PayloadDecoder {
    public static func decode<T: Decodable>(_ type: T.Type, json: String) throws -> T {
        try JSONDecoder().decode(type, from: Data(json.utf8))
    }
}
