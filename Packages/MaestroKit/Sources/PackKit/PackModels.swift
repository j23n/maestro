import Foundation
import ItalianCore

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

    public var sentences: [Sentence] { blocks.flatMap(\.sentences) }

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
    public let text: String
    public let sentences: [Sentence]
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
    public let gn: String?
    public let gloss: String?
    public let note: String?
    public let grammar: [String]?
    public let parts: [TokenPart]?

    public var isWord: Bool { pos != "PUNCT" }
    public var formTag: FormTag? { form.flatMap(FormTag.init) }
    public var genderNumber: GenderNumber? { gn.flatMap(GenderNumber.init(rawValue:)) }
}

public struct TokenPart: Codable, Sendable, Hashable {
    public let t: String
    public let pos: String?
    public let lemmaID: String?
    public let senseID: String?
    public let form: String?
    public let gn: String?
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

    /// The choices to show, in Italian or English.
    public func choices(english: Bool) -> [String] {
        switch type {
        case .choice: (english ? optionsEN : options) ?? []
        case .yesNoNotStated: english ? ["Yes", "No", "Not stated"] : ["Sì", "No", "Non si dice"]
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
