import Foundation
import LanguageCore

/// Pack format, HANDOFF.md 6.3 (formatVersion 1). Unknown keys such as "$note" are ignored.
public struct PackManifest: Codable, Sendable, Hashable, Identifiable {
    public let id: String
    public let title: String
    public let level: String
    public let formatVersion: Int
    public let version: Int
    public let minContentDB: String
    public let language: String
    public let translationLanguage: String
    public let texts: [TextEntry]

    public struct TextEntry: Codable, Sendable, Hashable, Identifiable {
        public let id: String
        public let order: Int
        public let title: String
        public let level: String?
        public let file: String
        public let words: Int
        public let topics: [String]?
        public let grammar: GrammarUse?
        public let lemmas: [String]?
        /// When the library features the text, such as `12-01..01-06` (see `FeatureWindow`).
        public let window: String?
        /// `draft` until a native speaker has reviewed the text; absent once reviewed.
        public let status: String?

        public var featureWindow: FeatureWindow? { window.flatMap { FeatureWindow($0) } }
        public var isDraft: Bool { status == "draft" }
    }

    public struct GrammarUse: Codable, Sendable, Hashable {
        public let introduces: [String]
        public let uses: [String]
    }
}

public struct ReadingText: Codable, Sendable, Hashable, Identifiable {
    public let id: String
    public let title: String
    public let level: String
    public let collection: String
    public let blocks: [Block]
    public let questions: [Question]
    /// The session's drills after the text, every strand (HANDOFF.md 3.9); absent in packs built before drills.
    public let drills: [Drill]?
    /// The Words strand's intro: the text's new words, in order.
    public let newWords: [NewWord]?
    /// The Verbs strand's intro: the verbs the strand drills.
    public let verbs: [TextVerb]?
    /// The Say it strand's intro: what the text's people do with language.
    public let functions: [TextFunction]?

    public var sentences: [Sentence] { blocks.flatMap(\.sentences) }

    /// Drills this app version can show, in pack order.
    public var practice: [Drill] { (drills ?? []).filter { $0.format != nil } }

    /// A drill by its stable key.
    public func drill(key: String) -> Drill? { drills?.first { $0.stableKey == key } }

    public func sentence(_ id: String) -> Sentence? { sentences.first { $0.id == id } }

    public var wordCount: Int {
        sentences.reduce(0) { $0 + $1.tokens.filter { $0.pos != "PUNCT" }.count }
    }
}

public enum BlockType: String, Codable, Sendable, Hashable {
    case prose, dialogue, message, list, sign, verse
}

public struct Block: Codable, Sendable, Hashable {
    public let type: BlockType
    public let speaker: String?
    /// The speaker's gender, `m` or `f`, from the text's `speakers:` line; absent when not given.
    public let gender: String?
    public let text: String
    public let sentences: [Sentence]

    public var speakerGender: SpeakerGender? { gender.flatMap(SpeakerGender.init(rawValue:)) }
}

/// A dialogue speaker's gender, which picks the voice that reads their lines.
public enum SpeakerGender: String, Codable, Sendable, Hashable {
    case female = "f"
    case male = "m"
}

public struct Sentence: Codable, Sendable, Hashable, Identifiable {
    public let id: String
    public let r: UTF16Range
    public let text: String
    public let translation: String
    public let tokens: [Token]
    public let units: [Unit]?

    /// The unit a token belongs to, if any.
    public func unit(containing tokenIndex: Int) -> Unit? {
        units?.first { $0.tokens.contains(tokenIndex) }
    }

    /// The tokens a text offset (UTF-16, within the sentence) falls into.
    public func tokenIndex(at offset: Int) -> Int? {
        tokens.firstIndex { $0.r.contains(offset) }
    }
}

public struct Token: Codable, Sendable, Hashable {
    public let t: String
    public let r: UTF16Range
    public let pos: String?
    public let lemmaID: String?
    public let senseID: String?
    public let form: String?
    public let agree: String?
    /// Italian `ms` `fs` `mp` `fp`; German `ms` `fs` `ns` `pl`.
    public let gn: String?
    /// German case: `nom` `acc` `dat` `gen` (HANDOFF.md 6.5).
    public let `case`: String?
    /// A German adjective's declension: `str` `wk` `mix`.
    public let decl: String?
    public let gloss: String?
    public let note: String?
    public let grammar: [String]?
    public let parts: [TokenPart]?

    public var isWord: Bool { pos != "PUNCT" }
    public var formTag: FormTag? { form.flatMap(FormTag.init) }
    public var genderNumber: GenderNumber? { gn.flatMap(GenderNumber.init(rawValue:)) }
    /// A German token's case, number and declension, such as Dativ neutral Singular.
    public var caseTag: CaseTag? { CaseTag(case: `case`, gn: gn, decl: decl) }
}

public struct TokenPart: Codable, Sendable, Hashable {
    public let t: String
    public let pos: String?
    public let lemmaID: String?
    public let senseID: String?
    public let form: String?
    public let gn: String?
    public let `case`: String?

    public var caseTag: CaseTag? { CaseTag(case: `case`, gn: gn, decl: nil) }
}

extension CaseTag {
    /// From a pack token's separate `case`, `gn` and `decl` fields; nil without a case.
    init?(case grammaticalCase: String?, gn: String?, decl: String?) {
        guard let c = grammaticalCase.flatMap(Case.init(rawValue:)) else { return nil }
        self.init(declension: decl.flatMap(Declension.init(rawValue:)), grammaticalCase: c,
                  number: gn.flatMap(Number.init(rawValue:)))
    }
}

public struct Unit: Codable, Sendable, Hashable {
    public let tokens: [Int]
    public let surface: String
    public let lemmaID: String?
    public let senseID: String?
    public let form: String?
    public let agree: String?
    public let gloss: String?
    public let grammar: [String]?
    public let note: String?

    public var formTag: FormTag? { form.flatMap(FormTag.init) }
}

public enum QuestionType: String, Codable, Sendable, Hashable {
    case choice, yesNoNotStated
}

public enum QuestionAnswer: Codable, Sendable, Hashable {
    case option(Int)
    case value(String)   // yes | no | notStated

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let i = try? container.decode(Int.self) {
            self = .option(i)
        } else {
            self = .value(try container.decode(String.self))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .option(let i): try container.encode(i)
        case .value(let s): try container.encode(s)
        }
    }
}

public struct Question: Codable, Sendable, Hashable, Identifiable {
    public let id: String
    public let type: QuestionType
    public let prompt: String
    public let promptEN: String
    public let options: [String]?
    public let optionsEN: [String]?
    public let answer: QuestionAnswer
    public let answerSentences: [String]

    /// The choices to show, in the text's language or English.
    public func choices(english: Bool, language: Language = .it) -> [String] {
        switch type {
        case .choice: (english ? optionsEN : options) ?? []
        case .yesNoNotStated:
            if english { ["Yes", "No", "Not stated"] } else {
                switch language {
                case .it: ["Sì", "No", "Non si dice"]
                case .de: ["Ja", "Nein", "Steht nicht im Text"]
                }
            }
        }
    }

    /// Whether the choice at this index is the right one.
    public func isCorrect(_ index: Int) -> Bool {
        switch (type, answer) {
        case (.choice, .option(let i)): index == i
        case (.yesNoNotStated, .value(let v)): ["yes", "no", "notStated"].firstIndex(of: v) == index
        default: false
        }
    }
}

/// A drill's format. Packs may add formats later; the app skips ones it doesn't know.
public enum DrillFormat: String, Codable, Sendable, Hashable {
    case choice, gap, match, build
    /// Tap every target word in a few lines of the text.
    case find
    /// Fill the blank cells of one verb's tense.
    case row
    /// Hear a word and type it into its gap.
    case listen
    /// Say a line from its English: an open answer graded by patterns.
    case say
    /// Take one side of the text's dialogue.
    case roleplay
}

/// A session strand (HANDOFF.md 3.9). Drills from packs without strands are grammar.
public enum Strand: String, Codable, Sendable, Hashable, CaseIterable {
    case words, grammar, verbs, say
}

/// A word a `find` drill wants tapped: token `t` of sentence `s`.
public struct DrillTarget: Codable, Sendable, Hashable {
    public let s: String
    public let t: Int

    public init(s: String, t: Int) {
        self.s = s
        self.t = t
    }
}

/// One person of a `row` drill. `forms[0]` is shown; any of `forms` is accepted.
public struct RowCell: Codable, Sendable, Hashable {
    public let p: String
    public let label: String
    public let forms: [String]
    public let given: Bool

    public init(p: String, label: String, forms: [String], given: Bool) {
        self.p = p
        self.label = label
        self.forms = forms
        self.given = given
    }
}

/// What the learner sets out to do in a role-play, such as "Accept".
public struct RoleplayGoal: Codable, Sendable, Hashable, Identifiable {
    public let id: String
    public let label: String

    public init(id: String, label: String) {
        self.id = id
        self.label = label
    }
}

/// One line of a role-play: the other side's (`chips` absent), or the learner's, picked from `chips`
/// or typed and graded by `accept` patterns. `s` are the text's sentences the line is.
public struct RoleplayTurn: Codable, Sendable, Hashable {
    public let who: String
    public let s: [String]
    public let chips: [String]?
    public let answers: [String]?
    public let accept: [String]?
    public let goal: String?

    public var isLearner: Bool { chips != nil }

    public init(who: String, s: [String], chips: [String]? = nil, answers: [String]? = nil,
                accept: [String]? = nil, goal: String? = nil) {
        self.who = who
        self.s = s
        self.chips = chips
        self.answers = answers
        self.accept = accept
        self.goal = goal
    }
}

/// A new word of a text, for the Words strand's intro.
public struct NewWord: Codable, Sendable, Hashable {
    public let lemmaID: String
    public let senseID: String?
    public let word: String
    public let surface: String
    public let gloss: String
    public let sentence: String
    public let r: UTF16Range
}

/// A verb the Verbs strand drills, for its intro: the form as it appears and its label.
public struct TextVerb: Codable, Sendable, Hashable {
    public let lemmaID: String
    public let word: String
    public let surface: String
    public let form: String
    public let sentence: String
    public let r: UTF16Range
}

/// A communicative function the text uses (`functions.yaml`), for the Say it strand's intro.
public struct TextFunction: Codable, Sendable, Hashable {
    public let id: String
    public let name: String
    public let label: String
}

/// One drill of a session (HANDOFF.md 3.9), generated at pack build time from the text's sentences.
///
/// - `choice`, `gap` and `listen`: `before` + the answer + `after` is the sentence; `r` is the gap's UTF-16
///   range in it. Without a gap, the sentence is shown whole with `focus` marked and the answer goes below.
///   `listen` speaks `speak`. `optionLang` "en" means the options are English.
/// - `match`: `pairs` to join, such as a verb and its participle, or a word and its meaning.
/// - `build`: `tiles` (plus `distractors`) to put in the order of `answers[0]`, words joined by spaces.
/// - `find`: tap every `targets` token in the lines `sentences`.
/// - `row`: fill the `cells` that aren't `given`, of the verb `cue` in the tense `tense`.
/// - `say`: say `cue` (English) in the language; any answer the `accept` patterns allow counts.
/// - `roleplay`: be `speaker` and talk to `other` through `turns`, reaching `goals`.
public struct Drill: Codable, Sendable, Hashable, Identifiable {
    public let id: String
    public let kind: String
    public let recipe: String
    public let topic: String
    public let sentence: String
    public let prompt: String
    public let before: String?
    public let after: String?
    public let r: UTF16Range?
    public let cue: String?
    public let options: [String]?
    public let answers: [String]?
    /// Wrong answers the drill expects, keyed by their folded form (`Normalizer.fold`), with a hint for each.
    public let near: [String: String]?
    public let hint: String?
    public let rule: String?
    public let pairs: [[String]]?
    public let sentences: [String]?
    public let tiles: [String]?
    public let distractors: [String]?
    public let translation: String?
    public let recycled: Bool?
    /// The session strand; nil in packs from before sessions, which only had grammar.
    public let strand: String?
    /// Whether a Short session includes it.
    public let core: Bool?
    /// A hash of what the drill asks, the same from build to build (unlike `id`).
    public let key: String?
    /// The word to look at when the sentence has no gap.
    public let focus: UTF16Range?
    /// "en" when the options (or a match's right side) are English.
    public let optionLang: String?
    /// The lemma a Words or Verbs drill is about.
    public let lemma: String?
    /// The communicative function a Say it drill is about.
    public let function: String?
    public let speak: String?
    public let targets: [DrillTarget]?
    public let cells: [RowCell]?
    public let tense: String?
    /// What a `say` drill asks for, such as "Accepting".
    public let label: String?
    public let accept: [String]?
    /// Other ways to say it, shown after a `say` drill.
    public let also: [String]?
    public let speaker: String?
    public let other: String?
    public let goals: [RoleplayGoal]?
    public let turns: [RoleplayTurn]?

    public var format: DrillFormat? { DrillFormat(rawValue: kind) }
    public var isRecycled: Bool { recycled ?? false }
    public var strandKind: Strand { strand.flatMap(Strand.init(rawValue:)) ?? .grammar }
    public var isCore: Bool { core ?? false }
    public var englishOptions: Bool { optionLang == "en" }
    /// The key outcomes are stored under: the pack's key, or for older packs the text's drill ID.
    public var stableKey: String { key ?? id }
    /// Whether the drill is about German, so its answers keep umlauts (DrillGrader).
    public var isGerman: Bool { topic.hasPrefix("de:") || (lemma?.hasPrefix("de:") ?? false) }
    /// The first accepted answer, the one the sentence itself has.
    public var answer: String { answers?.first ?? "" }

    public init(id: String, kind: String, recipe: String, topic: String, sentence: String, prompt: String,
                before: String? = nil, after: String? = nil, r: UTF16Range? = nil, cue: String? = nil,
                options: [String]? = nil, answers: [String]? = nil, near: [String: String]? = nil,
                hint: String? = nil, rule: String? = nil, pairs: [[String]]? = nil, sentences: [String]? = nil,
                tiles: [String]? = nil, distractors: [String]? = nil, translation: String? = nil,
                recycled: Bool? = nil, strand: String? = nil, core: Bool? = nil, key: String? = nil,
                focus: UTF16Range? = nil, optionLang: String? = nil, lemma: String? = nil, function: String? = nil,
                speak: String? = nil, targets: [DrillTarget]? = nil, cells: [RowCell]? = nil, tense: String? = nil,
                label: String? = nil, accept: [String]? = nil, also: [String]? = nil, speaker: String? = nil,
                other: String? = nil, goals: [RoleplayGoal]? = nil, turns: [RoleplayTurn]? = nil) {
        self.id = id
        self.kind = kind
        self.recipe = recipe
        self.topic = topic
        self.sentence = sentence
        self.prompt = prompt
        self.before = before
        self.after = after
        self.r = r
        self.cue = cue
        self.options = options
        self.answers = answers
        self.near = near
        self.hint = hint
        self.rule = rule
        self.pairs = pairs
        self.sentences = sentences
        self.tiles = tiles
        self.distractors = distractors
        self.translation = translation
        self.recycled = recycled
        self.strand = strand
        self.core = core
        self.key = key
        self.focus = focus
        self.optionLang = optionLang
        self.lemma = lemma
        self.function = function
        self.speak = speak
        self.targets = targets
        self.cells = cells
        self.tense = tense
        self.label = label
        self.accept = accept
        self.also = also
        self.speaker = speaker
        self.other = other
        self.goals = goals
        self.turns = turns
    }
}
