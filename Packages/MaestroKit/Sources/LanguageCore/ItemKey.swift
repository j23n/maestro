import Foundation

/// The three kinds of thing a learner can keep in Remember (HANDOFF.md 3.4).
public enum ItemKind: String, Sendable, Codable, CaseIterable, Hashable {
    case word, verbForm, grammar

    public var label: String {
        switch self {
        case .word: "Word"
        case .verbForm: "Verb form"
        case .grammar: "Grammar"
        }
    }

    public var prompt: String {
        switch self {
        case .word: "What does it mean?"
        case .verbForm: "Which verb, tense and person?"
        case .grammar: "What is this construction, and how would you say it in English?"
        }
    }
}

/// Item keys identify a kept item across devices and link review logs to it (HANDOFF.md 6.5).
public enum ItemKey {
    public static func word(lemmaID: String, senseID: String) -> String { "word|\(lemmaID)|\(senseID)" }
    public static func verbForm(lemmaID: String, formTag: String) -> String { "verbForm|\(lemmaID)|\(formTag)" }
    public static func grammar(_ grammarID: String) -> String { "grammar|\(grammarID)" }

    public static func kind(of key: String) -> ItemKind? {
        guard let head = key.split(separator: "|", maxSplits: 1).first else { return nil }
        return ItemKind(rawValue: String(head))
    }

    /// The key with its IDs passed through `resolve` (redirects); nil if any ID is unknown.
    public static func resolved(_ key: String, resolve: (String) -> String?) -> String? {
        let parts = key.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
        guard let kind = parts.first.flatMap(ItemKind.init(rawValue:)) else { return nil }
        switch kind {
        case .word where parts.count == 3:
            guard let lemma = resolve(parts[1]), let sense = resolve(parts[2]) else { return nil }
            return word(lemmaID: lemma, senseID: sense)
        case .verbForm where parts.count == 3:
            guard let lemma = resolve(parts[1]) else { return nil }
            return verbForm(lemmaID: lemma, formTag: parts[2])
        case .grammar where parts.count == 2:
            guard let id = resolve(parts[1]) else { return nil }
            return grammar(id)
        default:
            return nil
        }
    }
}

public enum Level: String, Sendable, Codable, CaseIterable, Comparable, Hashable {
    case a1 = "A1", a2 = "A2", b1 = "B1", b2 = "B2"

    public var name: String {
        switch self {
        case .a1: "Beginner"
        case .a2: "Elementary"
        case .b1: "Intermediate"
        case .b2: "Upper intermediate"
        }
    }

    public static func < (lhs: Level, rhs: Level) -> Bool {
        allCases.firstIndex(of: lhs)! < allCases.firstIndex(of: rhs)!
    }
}

/// Lemma IDs: it:<headword>:<pos>[:<n>].
public enum LemmaID {
    public static func headword(of id: String) -> String {
        let parts = id.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count >= 3 else { return id }
        return parts[1].replacingOccurrences(of: "_", with: " ")
    }

    public static func pos(of id: String) -> String {
        let parts = id.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count >= 3 else { return "" }
        return String(parts[2])
    }

    /// The lemma part of a sense ID.
    public static func of(senseID: String) -> String {
        String(senseID.split(separator: "#", maxSplits: 1).first ?? Substring(senseID))
    }
}
