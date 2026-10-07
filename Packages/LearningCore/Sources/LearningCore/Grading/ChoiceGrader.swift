import Foundation

/// Choice, true-false and sound-pair grading: the selection equals the answer (docs/05 § Other graders).
/// Indices refer to options as written; the seeded display shuffle is undone by the caller.
public enum ChoiceGrader {
    /// `choice` (and `sound-pair` which-word): the selected option index against `answer`.
    public static func grade(selected: Int, answer: Int) -> GradedAnswer {
        GradedAnswer(outcome: selected == answer ? .correct : .wrong, selectedIndex: selected)
    }

    /// `true-false`.
    public static func grade(selected: Bool, answer: Bool) -> GradedAnswer {
        GradedAnswer(outcome: selected == answer ? .correct : .wrong, selectedIndex: selected ? 0 : 1)
    }

    /// Any other single selection (`sound-pair` single-or-double).
    public static func grade<T: Equatable>(selected: T, answer: T) -> GradedAnswer {
        GradedAnswer(outcome: selected == answer ? .correct : .wrong)
    }
}

/// `match` grading: each pair is scored on its own, and its outcome goes to that pair's target (docs/05).
public enum MatchGrader {
    public struct Result: Sendable, Hashable {
        /// One outcome per pair as written (`correct` or `wrong`).
        public let pairOutcomes: [AttemptOutcome]
        /// `correct` when every pair is right.
        public var outcome: AttemptOutcome { pairOutcomes.allSatisfy { $0 == .correct } ? .correct : .wrong }
        public var answer: GradedAnswer { GradedAnswer(outcome: outcome) }
    }

    /// `selections[left] = right`, both as written; pair `i` is right when its left item was matched with
    /// right item `i`. A pair with no selection is wrong.
    public static func grade(selections: [Int: Int], pairCount: Int) -> Result {
        Result(pairOutcomes: (0..<pairCount).map { selections[$0] == $0 ? .correct : .wrong })
    }

    /// Whether one tap pairing `left` with `right` is right (for marking a pair as the learner makes it).
    public static func isMatch(left: Int, right: Int) -> Bool { left == right }
}
