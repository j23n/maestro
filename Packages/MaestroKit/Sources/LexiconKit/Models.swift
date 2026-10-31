import Foundation
import ItalianCore

public struct LemmaSummary: Sendable, Hashable, Identifiable {
    public let id: String
    public let headword: String
    public let pos: String
    public let gender: String?
    public let firstGloss: String

    public init(id: String, headword: String, pos: String, gender: String?, firstGloss: String) {
        self.id = id
        self.headword = headword
        self.pos = pos
        self.gender = gender
        self.firstGloss = firstGloss
    }

    /// "verb", "noun", ...
    public var posLabel: String { PartOfSpeech.label(pos) }
}

public enum PartOfSpeech {
    public static func label(_ pos: String) -> String {
        switch pos {
        case "v": "verb"
        case "n": "noun"
        case "adj": "adjective"
        case "adv": "adverb"
        case "prep": "preposition"
        case "art": "article"
        case "conj": "conjunction"
        case "pron": "pronoun"
        case "det": "determiner"
        case "num": "number"
        case "intj": "interjection"
        case "propn": "proper noun"
        case "phr": "phrase"
        case "contr": "contraction"
        default: pos
        }
    }
}

public struct Sense: Sendable, Hashable, Identifiable {
    public let id: String
    public let lemmaID: String
    public let gloss: String
    public let tags: [String]
    public let retired: Bool
    public var examples: [Example]
}

public struct Example: Sendable, Hashable {
    public let italian: String
    public let english: String?
}

public struct Entry: Sendable, Hashable, Identifiable {
    public let id: String
    public let headword: String
    public let pos: String
    public let gender: String?
    public let plural: String?
    public let ipa: String?
    public let auxiliary: String?
    public let senses: [Sense]

    /// "il treno", "la pesca", "l'anno"; the bare headword for anything but a noun.
    public var headwordWithArticle: String {
        guard pos == "n", let gender else { return headword }
        return Articles.definite(for: headword, gender: gender.hasPrefix("f") ? "f" : "m") + headword
    }

    public var genderLabel: String? {
        switch gender {
        case "m": "masculine"
        case "f": "feminine"
        case "mf": "masculine or feminine"
        default: nil
        }
    }
}

public enum Articles {
    private static let vowels: Set<Character> = ["a", "e", "i", "o", "u", "à", "è", "é", "ì", "ò", "ù", "h"]

    /// The singular definite article with its trailing space or apostrophe.
    public static func definite(for word: String, gender: String) -> String {
        let lower = word.lowercased()
        guard let first = lower.first else { return "" }
        if vowels.contains(first) && first != "h" { return "l'" }
        if gender == "f" { return "la " }
        let second = lower.dropFirst().first
        if first == "z" || first == "x" || first == "y" || lower.hasPrefix("gn") || lower.hasPrefix("ps")
            || lower.hasPrefix("pn") || (first == "s" && second.map { !vowels.contains($0) } == true)
            || (first == "i" && second.map { vowels.contains($0) } == true) {
            return "lo "
        }
        return "il "
    }
}

/// One way to read a looked-up form: lemma plus the analysis of this form.
public struct Reading: Sendable, Hashable, Identifiable {
    public enum Via: Sendable, Hashable {
        case headword
        case form
        case clitics(base: String, clitics: [String])
        case tagger
    }

    public let lemma: LemmaSummary
    public let formTag: FormTag?
    public let genderNumber: GenderNumber?
    public let surface: String
    public let via: Via

    public init(lemma: LemmaSummary, formTag: FormTag?, genderNumber: GenderNumber?, surface: String, via: Via) {
        self.lemma = lemma
        self.formTag = formTag
        self.genderNumber = genderNumber
        self.surface = surface
        self.via = via
    }

    public var id: String { "\(lemma.id)|\(formTag?.description ?? genderNumber?.rawValue ?? "")|\(surface)" }

    /// "andare · indicativo imperfetto · noi" or "canto · noun, masculine plural".
    public var analysis: String {
        if let formTag { return "\(lemma.headword) · \(formTag.label)" }
        if let genderNumber { return "\(lemma.headword) · \(lemma.posLabel), \(genderNumber.label)" }
        return "\(lemma.headword) · \(lemma.posLabel)"
    }
}

public enum LookupOutcome: Sendable, Equatable {
    /// One or more readings (an ambiguous form lists all of them).
    case readings([Reading])
    /// No exact match; these are close ("did you mean").
    case suggestions([LemmaSummary])
    /// Several words that aren't a dictionary phrase: offer sentence translation.
    case phrase(String)
    case empty
}
