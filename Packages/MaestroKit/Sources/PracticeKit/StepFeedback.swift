import Foundation

/// How a drill ended. The wrap-up shows it, and the session stores it on the device for Review
/// (`DrillRecord`, the app's `DrillLog`).
public enum Outcome: String, Sendable, Hashable, CaseIterable {
    case firstTry, afterHint, shown

    public var label: String {
        switch self {
        case .firstTry: "First try"
        case .afterHint: "After a hint"
        case .shown: "Answer shown"
        }
    }
}

/// Stepped feedback (HANDOFF.md 3.9): a first miss shows a hint and allows one more try; a second
/// miss shows the answer and the rule. "Show answer" ends the drill at any time. No scores, no lives.
public struct StepFeedback: Sendable, Equatable {
    public enum Phase: Sendable, Equatable {
        case answering
        case retrying
        case done(Outcome)
    }

    public private(set) var phase: Phase = .answering
    /// Whether the learner has seen a hint: asked for one, or got one after a miss.
    public private(set) var sawHint = false

    public init() {}

    public var isDone: Bool {
        if case .done = phase { return true }
        return false
    }

    public var outcome: Outcome? {
        if case .done(let o) = phase { return o }
        return nil
    }

    /// "Show a hint" before answering.
    public mutating func showHint() {
        if !isDone { sawHint = true }
    }

    /// Records an answer and returns the new phase.
    @discardableResult
    public mutating func record(accepted: Bool) -> Phase {
        switch phase {
        case .answering:
            if accepted {
                phase = .done(sawHint ? .afterHint : .firstTry)
            } else {
                phase = .retrying
                sawHint = true
            }
        case .retrying:
            phase = .done(accepted ? .afterHint : .shown)
        case .done:
            break
        }
        return phase
    }

    /// "Show answer".
    public mutating func reveal() {
        if !isDone { phase = .done(.shown) }
    }

    /// Ends a drill whose parts are graded one by one (match): a first try only if nothing was missed.
    public mutating func finish(missed: Bool) {
        if !isDone { phase = .done(missed || sawHint ? .afterHint : .firstTry) }
    }
}
