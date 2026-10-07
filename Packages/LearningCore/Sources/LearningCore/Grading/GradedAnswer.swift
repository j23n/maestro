import Foundation

/// What a mismatch looks like, for the generic hints (docs/05 § Stepped feedback; `fixtures/grading/typed-answers.json`).
public enum HintKind: String, Codable, Sendable, CaseIterable {
    /// A token of the answer is missing (deletion).
    case missing
    /// The response has a token too many (insertion).
    case extra
    /// Another form of the expected item (an inflection error: *americana* for *americano*).
    case ending
    /// A known form of a different item (*te* for *tè*).
    case realWord
    /// Anything else: a misspelling, an accent, an unknown word.
    case spelling

    /// The generic hint text (docs/05 § Stepped feedback). The app may localise by `rawValue`.
    public var genericHint: String {
        switch self {
        case .realWord: "That's a real word, but not the one we need here."
        case .spelling: "Check the spelling."
        case .ending: "Check the ending."
        case .missing: "Something's missing."
        case .extra: "There's an extra word."
        }
    }
}

/// One graded answer, in the shape the `FeedbackMachine` needs, whatever grader produced it.
public struct GradedAnswer: Sendable, Hashable {
    /// `correct`, `correctWithNote`, `almost` or `wrong`.
    public var outcome: AttemptOutcome
    /// The kind of the first mismatch, for the generic hint.
    public var hintKind: HintKind?
    /// The hint of a matched `near` entry.
    public var nearHint: String?
    /// Mismatched token indices (into the expected answer) for underlining.
    public var mismatches: [Int]
    /// For tapped formats: the option chosen (as written), so a wrong first choice can be marked.
    public var selectedIndex: Int?

    public init(
        outcome: AttemptOutcome, hintKind: HintKind? = nil, nearHint: String? = nil, mismatches: [Int] = [],
        selectedIndex: Int? = nil
    ) {
        self.outcome = outcome
        self.hintKind = hintKind
        self.nearHint = nearHint
        self.mismatches = mismatches
        self.selectedIndex = selectedIndex
    }
}
