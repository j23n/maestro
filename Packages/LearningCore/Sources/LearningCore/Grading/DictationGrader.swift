import Foundation

/// Grades a dictation word by word (docs/05 § Other graders; `fixtures/grading/dictation.json`).
///
/// Each target word is marked `correct`, `accent` (only accents differ), `doubling` (only single versus double
/// consonants differ, even in a 3-letter word: *eco*/*ecco*), `typo` (the typed-answer rule: Damerau-Levenshtein
/// 1, at least 4 letters, not another form of the same item) or `wrong` (anything else, or missing). Accent
/// slips on accent-sensitive words (*e*/*è*) are `wrong`: they are different words. Outcome: all correct →
/// `correct`; only accent, doubling or typo marks → `almost`; any wrong mark or extra word → `wrong`.
public enum DictationGrader {
    public enum Mark: String, Sendable, Hashable, Codable {
        case correct, accent, doubling, typo, wrong
    }

    /// One target word and how the learner wrote it.
    public struct Word: Sendable, Hashable {
        public let mark: Mark
        /// The target word (normalised).
        public let expected: String
        /// What the learner typed in its place (nil when missing).
        public let typed: String?
        /// For a `doubling` mark: the consonant, and whether the target has it doubled — for the note
        /// "Listen again: cornetto has a double t".
        public let consonant: Character?
        public let targetIsDouble: Bool?
    }

    public struct Result: Sendable, Hashable {
        public let outcome: AttemptOutcome
        /// One per target word, in order.
        public let words: [Word]
        /// Response tokens that match no target word.
        public let extraWords: [String]

        public var marks: [Mark] { words.map(\.mark) }
    }

    public static func grade(target: String, response: String, knownForms: KnownForms = .empty) -> Result {
        let expected = Normalizer.tokens(target)
        let typed = Normalizer.tokens(response)
        let (_, ops) = TokenAligner.align(
            expectedCount: expected.count, responseCount: typed.count,
            slotRange: { _ in nil }, slotAccepts: { _, _ in false },
            pair: { i, j in pairing(expected[i], typed[j], knownForms) })

        var words: [Word] = []
        var extra: [String] = []
        for op in ops {
            switch op {
            case .pair(let e, let r, let mark):
                let doubling =
                    mark == .doubling ? EditDistance.doublingDifference(target: expected[e], response: typed[r]) : nil
                words.append(
                    Word(
                        mark: mark, expected: expected[e], typed: typed[r], consonant: doubling?.consonant,
                        targetIsDouble: doubling?.targetIsDouble))
            case .delete(let e):
                words.append(Word(mark: .wrong, expected: expected[e], typed: nil, consonant: nil, targetIsDouble: nil))
            case .insert(let r):
                extra.append(typed[r])
            case .slot:
                break
            }
        }
        let outcome: AttemptOutcome
        if !extra.isEmpty || words.contains(where: { $0.mark == .wrong }) {
            outcome = .wrong
        } else if words.allSatisfy({ $0.mark == .correct }) {
            outcome = .correct
        } else {
            outcome = .almost
        }
        return Result(outcome: outcome, words: words, extraWords: extra)
    }

    static func pairing(_ e: String, _ r: String, _ knownForms: KnownForms) -> TokenAligner.Pairing<Mark> {
        if e == r { return .init(mark: .correct, cost: 0, hard: false) }
        let sameItem = knownForms.areFormsOfSameItem(e, r)
        let se = Normalizer.stripAccents(e)
        let sr = Normalizer.stripAccents(r)
        if se == sr {
            let sensitive = Normalizer.isAccentSensitive(e) || Normalizer.isAccentSensitive(r)
            return sensitive || sameItem
                ? .init(mark: .wrong, cost: 10, hard: true) : .init(mark: .accent, cost: 1, hard: false)
        }
        if !sameItem, EditDistance.doublingDifference(target: e, response: r) != nil {
            return .init(mark: .doubling, cost: 2, hard: false)
        }
        if !sameItem, se.count >= 4, EditDistance.isOneEdit(se, sr) {
            return .init(mark: .typo, cost: 5, hard: false)
        }
        return .init(mark: .wrong, cost: 10, hard: true)
    }
}
