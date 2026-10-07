import Foundation

/// Stepped feedback for one exercise (docs/05 § Stepped feedback; ADR-09).
///
/// ```
/// awaitingFirst ──correct/correctWithNote──▶ done(success)        (show note if any)
///       │         ──almost─────────────────▶ done(successWithCorrection)
///       │         ──wrong──▶ hinted: underline mismatches; show near-miss hint ∥ exercise hint ∥ generic hint
///       │                     └─▶ awaitingSecond ──correct/correctWithNote/almost──▶ done(successAfterHint)
///       │                                        ──wrong──▶ answerShown: answer + one-line rule ──▶ done(failed)
///       └── "Show answer" (any time) ──▶ answerShown (outcome revealed)
///
/// check, final, placement: awaitingFirst ──any outcome──▶ done(recorded)     (nothing shown)
/// ```
///
/// Tapped formats run the same machine: a wrong first choice is marked (`markedWrongChoices`), the hint is shown
/// and one more choice is allowed. In check, final and placement contexts there is one attempt, no hint, no "Show
/// answer" and no feedback: every answer ends in `done(recorded)`, whatever its outcome (docs/06 § Unit check).
/// Every graded answer returns the `attempt` event fields the machine decides.
public struct FeedbackMachine: Sendable, Hashable {
    /// `attempt.feedbackShown`: the most help the learner had seen when the attempt was recorded — `hint` once a
    /// hint was on screen (asked for with "Show a hint", or after a first miss), `answer` when the answer was
    /// shown (a reveal).
    public enum FeedbackShown: String, Codable, Sendable, Hashable {
        case none, hint, answer
    }

    /// The fields of one `attempt` event that the machine decides (docs/05 § Events).
    public struct AttemptRecord: Sendable, Hashable {
        /// 1 or 2.
        public let attemptIndex: Int
        public let outcome: AttemptOutcome
        public let feedbackShown: FeedbackShown
    }

    /// The hint shown after a first miss: a near-miss hint, else the exercise's hint, else a generic hint chosen
    /// by the first mismatch.
    public enum Hint: Sendable, Hashable {
        case nearMiss(String)
        case exercise(String)
        case generic(HintKind)

        public var text: String {
            switch self {
            case .nearMiss(let s), .exercise(let s): s
            case .generic(let kind): kind.genericHint
            }
        }
    }

    public enum Result: Sendable, Hashable {
        /// Right first time (show the note, if any: accents for `correctWithNote`).
        case success
        /// `almost` first time: show the correction.
        case successWithCorrection
        /// Right (or almost) on the second attempt.
        case successAfterHint
        /// Missed twice, or the answer was shown.
        case failed
        /// "Skip — can't speak now" (speaking formats).
        case skipped
        /// Check, final and placement: the answer was recorded and nothing is shown; the learner moves on. Its
        /// outcome is in the returned `AttemptRecord` (and `lastAnswer`), for scoring and the result screen.
        case recorded
    }

    /// Why the answer is on screen.
    public enum AnswerReason: Sendable, Hashable {
        /// The learner tapped "Show answer" (outcome `revealed`).
        case revealed
        /// The second attempt was wrong too.
        case missedTwice
    }

    public enum State: Sendable, Hashable {
        case awaitingFirst
        /// After a wrong first answer: mismatches underlined, the hint (if there is one) shown, "Try again".
        case hinted(Hint?)
        /// The learner is trying again; the hint stays visible.
        case awaitingSecond(Hint?)
        /// The answer and the one-line rule are shown; "Continue" finishes.
        case answerShown(AnswerReason)
        case done(Result)
    }

    public let context: AttemptContext
    /// The exercise's authored `hint` (shown on request, and after a first wrong answer).
    public let exerciseHint: String?

    public private(set) var state: State = .awaitingFirst
    /// True once the learner asked for the hint before answering.
    public private(set) var hintRequested = false
    /// The last graded answer (its note or near-miss hint, mismatches to underline).
    public private(set) var lastAnswer: GradedAnswer?
    /// Tapped formats: options chosen wrongly, to mark and disable.
    public private(set) var markedWrongChoices: [Int] = []

    public init(context: AttemptContext, exerciseHint: String? = nil) {
        self.context = context
        self.exerciseHint = exerciseHint.flatMap { $0.isEmpty ? nil : $0 }
    }

    /// Check, final and placement: one attempt, no hint, no "Show answer".
    public var isSingleAttempt: Bool {
        switch context {
        case .check, .final, .placement: true
        case .lesson, .review: false
        }
    }

    public var isDone: Bool {
        if case .done = state { return true }
        return false
    }

    /// Whether "Show answer" is offered now.
    public var canShowAnswer: Bool {
        guard !isSingleAttempt else { return false }
        switch state {
        case .awaitingFirst, .hinted, .awaitingSecond: return true
        case .answerShown, .done: return false
        }
    }

    /// Whether "Show a hint" is offered now (only before the first answer, when the exercise has a hint).
    public var canRequestHint: Bool {
        !isSingleAttempt && state == .awaitingFirst && exerciseHint != nil && !hintRequested
    }

    /// "Show a hint" before answering. Returns the hint to show, or nil when there is none or it isn't allowed.
    /// After a miss it changes nothing and returns the hint already on screen (nil when there is none).
    public mutating func requestHint() -> Hint? {
        guard !isSingleAttempt else { return nil }
        switch state {
        case .awaitingFirst:
            guard let exerciseHint else { return nil }
            hintRequested = true
            return .exercise(exerciseHint)
        case .hinted(let hint), .awaitingSecond(let hint):
            return hint
        case .answerShown, .done:
            return nil
        }
    }

    /// Grades one answer. Returns the attempt to record, or nil when no answer is expected now.
    /// A `revealed` or `skipped` outcome is treated as `showAnswer()` or `skip()`.
    @discardableResult
    public mutating func submit(_ answer: GradedAnswer) -> AttemptRecord? {
        switch answer.outcome {
        case .revealed: return showAnswer()
        case .skipped: return skip()
        case .correct, .correctWithNote, .almost, .wrong: break
        }
        switch state {
        case .awaitingFirst:
            lastAnswer = answer
            let record = AttemptRecord(attemptIndex: 1, outcome: answer.outcome, feedbackShown: shownBeforeFirst)
            if isSingleAttempt {
                state = .done(.recorded)
                return record
            }
            switch answer.outcome {
            case .correct, .correctWithNote: state = .done(.success)
            case .almost: state = .done(.successWithCorrection)
            default:
                markWrongChoice(answer)
                state = .hinted(hint(for: answer))
            }
            return record
        case .hinted, .awaitingSecond:
            lastAnswer = answer
            let record = AttemptRecord(attemptIndex: 2, outcome: answer.outcome, feedbackShown: .hint)
            if answer.outcome == .wrong {
                markWrongChoice(answer)
                state = .answerShown(.missedTwice)
            } else {
                state = .done(.successAfterHint)
            }
            return record
        case .answerShown, .done:
            return nil
        }
    }

    /// "Try again" after a first miss.
    public mutating func tryAgain() {
        if case .hinted(let hint) = state { state = .awaitingSecond(hint) }
    }

    /// "Show answer": allowed any time before the answer is shown, except in check, final and placement contexts.
    @discardableResult
    public mutating func showAnswer() -> AttemptRecord? {
        guard !isSingleAttempt else { return nil }
        let index: Int
        switch state {
        case .awaitingFirst: index = 1
        case .hinted, .awaitingSecond: index = 2
        case .answerShown, .done: return nil
        }
        state = .answerShown(.revealed)
        return AttemptRecord(attemptIndex: index, outcome: .revealed, feedbackShown: .answer)
    }

    /// "Skip — can't speak now" (outcome `skipped`; docs/06 § Repeat after me).
    @discardableResult
    public mutating func skip() -> AttemptRecord? {
        let record: AttemptRecord
        switch state {
        case .awaitingFirst: record = AttemptRecord(attemptIndex: 1, outcome: .skipped, feedbackShown: shownBeforeFirst)
        case .hinted, .awaitingSecond: record = AttemptRecord(attemptIndex: 2, outcome: .skipped, feedbackShown: .hint)
        case .answerShown, .done: return nil
        }
        state = .done(.skipped)
        return record
    }

    /// "Continue" once the answer is shown.
    public mutating func acknowledgeAnswer() {
        if case .answerShown = state { state = .done(.failed) }
    }

    private var shownBeforeFirst: FeedbackShown { hintRequested ? .hint : .none }

    private mutating func markWrongChoice(_ answer: GradedAnswer) {
        if let index = answer.selectedIndex, !markedWrongChoices.contains(index) { markedWrongChoices.append(index) }
    }

    /// docs/05: near-miss hint ∥ exercise hint ∥ generic hint (by the first mismatch).
    func hint(for answer: GradedAnswer) -> Hint? {
        if let near = answer.nearHint, !near.isEmpty { return .nearMiss(near) }
        if let exerciseHint { return .exercise(exerciseHint) }
        return answer.hintKind.map { .generic($0) }
    }
}
