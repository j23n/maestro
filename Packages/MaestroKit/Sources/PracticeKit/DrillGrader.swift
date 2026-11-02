import Foundation
import ItalianCore
import PackKit

/// How an answer to a drill came out (HANDOFF.md 3.9).
public enum Grade: Sendable, Equatable {
    /// Accepted as given.
    case correct
    /// Accepted, but the accents differ from `expected` ("perche" for "perché").
    case accentSlip(expected: String)
    /// Not accepted; `hint` says what to look at.
    case wrong(hint: String)

    public var isAccepted: Bool {
        if case .wrong = self { return false }
        return true
    }
}

/// Grades typed, chosen and built answers. Pure, so it is the same on every device.
public enum DrillGrader {
    /// Lowercase, straight apostrophes, single spaces, no sentence punctuation.
    public static func normalize(_ text: String) -> String {
        let punctuation: Set<Character> = [".", ",", "!", "?", ";", ":", "«", "»", "\"", "“", "”"]
        let cleaned = String(Normalizer.query(text).map { punctuation.contains($0) ? " " : $0 })
        return cleaned.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }

    /// The key `Drill.near` uses: normalized, then without diacritics.
    public static func key(_ text: String) -> String { Normalizer.fold(normalize(text)) }

    /// A typed answer to a `gap` drill, or a typed version of a `choice` answer.
    public static func grade(_ answer: String, for drill: Drill) -> Grade {
        let given = normalize(answer)
        let accepted = drill.answers ?? []
        if accepted.contains(where: { normalize($0) == given }) { return .correct }
        if let match = accepted.first(where: { key($0) == key(given) }) { return .accentSlip(expected: match) }
        if let hint = drill.near?[key(given)] { return .wrong(hint: hint) }
        return .wrong(hint: genericHint(given, expected: normalize(drill.answer)))
    }

    /// A picked option of a `choice` drill.
    public static func grade(option: String, for drill: Drill) -> Grade {
        if (drill.answers ?? []).contains(option) { return .correct }
        return .wrong(hint: drill.near?[key(option)] ?? "Not that one. Read the sentence around the gap again.")
    }

    /// Tiles in order for a `build` drill.
    public static func grade(tiles: [String], for drill: Drill) -> Grade {
        let given = normalize(tiles.joined(separator: " "))
        if (drill.answers ?? []).contains(where: { normalize($0) == given }) { return .correct }
        let distractors = Set((drill.distractors ?? []).map(normalize))
        if tiles.contains(where: { distractors.contains(normalize($0)) }) {
            return .wrong(hint: "One of those words doesn't belong in the sentence.")
        }
        if tiles.count < (drill.tiles ?? []).count { return .wrong(hint: "Something's missing.") }
        return .wrong(hint: "Check the word order.")
    }

    /// The hint for a wrong answer the drill didn't expect.
    static func genericHint(_ given: String, expected: String) -> String {
        if given.isEmpty { return "Type an answer first." }
        let a = Array(Normalizer.fold(given)), b = Array(Normalizer.fold(expected))
        let shared = zip(a, b).prefix { $0 == $1 }.count
        if shared >= 3 || (shared >= 2 && b.count <= 4) { return "Check the ending." }
        if given.split(separator: " ").count < expected.split(separator: " ").count { return "Something's missing." }
        return "That's not the word we need here."
    }
}
