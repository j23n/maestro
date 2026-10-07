import Foundation

/// Sentence building: the tile order must equal one accepted order (docs/05 § Other graders).
public enum OrderGrader {
    public struct Result: Sendable, Hashable {
        public let outcome: AttemptOutcome
        /// The accepted order that was matched (when correct) or came closest (the longest common start).
        public let closestAnswer: Int?
        /// Position, in the learner's tile sequence, of the first tile that is out of place: the hint highlights
        /// it. Nil when correct, or when every placed tile is right but some are missing.
        public let firstMisplaced: Int?
        /// True when the placed tiles start an accepted order but stop short of it.
        public let isIncomplete: Bool

        public var answer: GradedAnswer { GradedAnswer(outcome: outcome) }
    }

    /// `placed` are the tile texts in the learner's order; `accepted` the accepted sentences. Both are
    /// compared normalised, so capitals and punctuation don't matter.
    public static func grade(placed: [String], accepted: [String]) -> Result {
        var tokens: [String] = []
        var tileOfToken: [Int] = []
        for (n, tile) in placed.enumerated() {
            for token in Normalizer.tokens(tile) {
                tokens.append(token)
                tileOfToken.append(n)
            }
        }
        var best: (index: Int, prefix: Int, length: Int)?
        for (index, answer) in accepted.enumerated() {
            let expected = Normalizer.tokens(answer)
            if expected == tokens {
                return Result(outcome: .correct, closestAnswer: index, firstMisplaced: nil, isIncomplete: false)
            }
            let prefix = zip(expected, tokens).prefix { $0 == $1 }.count
            if best == nil || prefix > (best?.prefix ?? 0) { best = (index, prefix, expected.count) }
        }
        guard let best else {
            return Result(
                outcome: .wrong, closestAnswer: nil, firstMisplaced: placed.isEmpty ? nil : 0, isIncomplete: false)
        }
        if best.prefix < tokens.count {
            return Result(
                outcome: .wrong, closestAnswer: best.index, firstMisplaced: tileOfToken[best.prefix],
                isIncomplete: false)
        }
        return Result(outcome: .wrong, closestAnswer: best.index, firstMisplaced: nil, isIncomplete: true)
    }
}
