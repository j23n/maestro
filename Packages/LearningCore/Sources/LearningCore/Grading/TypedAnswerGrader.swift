import Foundation

/// Grades a typed answer against accepted patterns (docs/05 § Typed answers): cloze, recall, generated cards and
/// typed conversation turns. `fixtures/grading/typed-answers.json` is the reference.
///
/// 1. A response equal to a `near` expansion returns that entry's outcome (default `wrong`) and hint.
/// 2. Otherwise the response tokens are aligned with every accepted expansion (token-level edit distance: equal 0;
///    accent-only 0.1 except accent-sensitive words; typo 0.5 = Damerau-Levenshtein 1 on a non-focus token of
///    ≥ 4 letters that is not another form of the same item; substitution, insertion, deletion 1). The cheapest
///    expansion wins. A response token that is another form of the expected token's item is an inflection error:
///    a substitution with hint kind `ending`, never a typo.
/// 3. Only accent differences → `correctWithNote`; accent or typo differences only → `almost`; else `wrong`.
public struct TypedAnswerGrader: Sendable {
    /// An anticipated wrong answer with a targeted hint (`near` in the content; docs/03).
    public struct NearMiss: Sendable, Hashable {
        public let pattern: AnswerPattern
        public let outcome: AttemptOutcome
        public let hint: String?

        public init(_ pattern: AnswerPattern, outcome: AttemptOutcome = .wrong, hint: String?) {
            self.pattern = pattern
            self.outcome = outcome
            self.hint = hint
        }

        public init(answer: String, outcome: AttemptOutcome = .wrong, hint: String?) throws(PatternError) {
            self.init(try AnswerPattern(answer), outcome: outcome, hint: hint)
        }
    }

    public let knownForms: KnownForms
    public let profile: LearnerProfile

    public init(knownForms: KnownForms = .empty, profile: LearnerProfile = .unspecified) {
        self.knownForms = knownForms
        self.profile = profile
    }

    /// Grades `response` against one accepted pattern.
    public func grade(_ response: String, accepted: AnswerPattern, near: [NearMiss] = []) -> TypedGrade {
        grade(response, accepted: [accepted], near: near)
    }

    /// Grades `response` against several accepted patterns (a conversation intent's `accept` list); the first
    /// pattern's first expansion is the model answer.
    public func grade(_ response: String, accepted: [AnswerPattern], near: [NearMiss] = []) -> TypedGrade {
        let tokens = Normalizer.tokens(response)
        let expansions = accepted.flatMap { $0.expansions(profile: profile) }.filter { profile.accepts($0.gender) }
        let best = bestAlignment(tokens, expansions)

        for entry in near {
            let matches = entry.pattern.expansions(profile: profile).contains { isExactMatch(tokens, $0) }
            if matches {
                return TypedGrade(
                    outcome: entry.outcome, alignment: best, responseTokens: tokens, nearHint: entry.hint,
                    matchedNear: true)
            }
        }
        guard let best else {
            return TypedGrade(
                outcome: .wrong, alignment: nil, responseTokens: tokens, nearHint: nil, matchedNear: false)
        }
        return TypedGrade(
            outcome: best.outcome, alignment: best, responseTokens: tokens, nearHint: nil, matchedNear: false)
    }

    // MARK: - Alignment

    struct Scored {
        var expansion: PatternExpansion
        var cost: TokenAligner.Cost
        var steps: [TypedGrade.Step]

        var outcome: AttemptOutcome {
            var accentOnly = true
            for step in steps {
                switch step.mark {
                case .equal, .slot: continue
                case .accent: continue
                case .typo: accentOnly = false
                case .substitution, .deletion, .insertion: return .wrong
                }
            }
            if steps.allSatisfy({ $0.mark == .equal || $0.mark == .slot }) { return .correct }
            return accentOnly ? .correctWithNote : .almost
        }
    }

    func bestAlignment(_ tokens: [String], _ expansions: [PatternExpansion]) -> Scored? {
        var best: Scored?
        for expansion in expansions {
            let scored = align(tokens, expansion)
            if let current = best, !(scored.cost < current.cost) { continue }
            best = scored
        }
        return best
    }

    /// A response equals an expansion when every word token is identical and every slot is filled (step 1).
    func isExactMatch(_ tokens: [String], _ expansion: PatternExpansion) -> Bool {
        let scored = align(tokens, expansion)
        return scored.steps.allSatisfy { $0.mark == .equal || $0.mark == .slot }
    }

    func align(_ tokens: [String], _ expansion: PatternExpansion) -> Scored {
        let expected = expansion.tokens
        let slots = Dictionary(expansion.slots.map { ($0.tokenIndex, $0.slot) }, uniquingKeysWith: { a, _ in a })
        let (cost, ops) = TokenAligner.align(
            expectedCount: expected.count, responseCount: tokens.count,
            slotRange: { slots[$0]?.wordRange },
            slotAccepts: { i, range in slots[i]?.accepts(tokens[range]) ?? false },
            pair: { i, j in
                pairing(expected: expected[i], response: tokens[j], focus: expansion.isFocus(i))
            })
        let steps = ops.map { op -> TypedGrade.Step in
            switch op {
            case .pair(let e, let r, let mark):
                return TypedGrade.Step(
                    mark: mark, expected: e, response: r..<(r + 1),
                    hintKind: hintKind(for: mark, expected: expected[e], response: tokens[r]))
            case .slot(let e, let r):
                return TypedGrade.Step(mark: .slot, expected: e, response: r, hintKind: nil)
            case .delete(let e):
                return TypedGrade.Step(mark: .deletion, expected: e, response: nil, hintKind: .missing)
            case .insert(let r):
                return TypedGrade.Step(mark: .insertion, expected: nil, response: r..<(r + 1), hintKind: .extra)
            }
        }
        return Scored(expansion: expansion, cost: cost, steps: steps)
    }

    /// docs/05 § Typed answers 2: the cost of pairing one expected token with one response token.
    func pairing(expected e: String, response r: String, focus: Bool) -> TokenAligner.Pairing<TypedGrade.Mark> {
        if e == r { return .init(mark: .equal, cost: 0, hard: false) }
        let se = Normalizer.stripAccents(e)
        let sr = Normalizer.stripAccents(r)
        let sameItem = knownForms.areFormsOfSameItem(e, r)
        if se == sr, !Normalizer.isAccentSensitive(e), !Normalizer.isAccentSensitive(r), !sameItem {
            return .init(mark: .accent, cost: 1, hard: false)
        }
        if !focus, !sameItem, se.count >= 4, EditDistance.isOneEdit(se, sr) {
            return .init(mark: .typo, cost: 5, hard: false)
        }
        return .init(mark: .substitution, cost: 10, hard: true)
    }

    func hintKind(for mark: TypedGrade.Mark, expected: String, response: String) -> HintKind? {
        switch mark {
        case .equal, .slot: return nil
        case .accent, .typo: return .spelling
        case .deletion: return .missing
        case .insertion: return .extra
        case .substitution:
            if knownForms.areFormsOfSameItem(expected, response) { return .ending }
            if knownForms.contains(response) { return .realWord }
            return .spelling
        }
    }
}

/// The result of grading a typed answer.
public struct TypedGrade: Sendable, Hashable {
    /// How one expected token compares with the response.
    public enum Mark: String, Sendable, Hashable {
        case equal, accent, typo, substitution, deletion, insertion
        /// A slot (`{NAME}`, `{NUMBER}` …) filled by response tokens.
        case slot
    }

    /// One step of the alignment, in reading order.
    public struct Step: Sendable, Hashable {
        public let mark: Mark
        /// Index into the expansion's tokens (nil for an inserted response token).
        public let expected: Int?
        /// Indices into the response tokens (nil for a missing expected token).
        public let response: Range<Int>?
        public let hintKind: HintKind?
    }

    /// `correct`, `correctWithNote`, `almost` or `wrong`.
    public let outcome: AttemptOutcome
    /// The accepted expansion the response came closest to (nil when nothing is accepted).
    public let expansion: PatternExpansion?
    /// The alignment with `expansion`.
    public let steps: [Step]
    /// The normalised response tokens.
    public let responseTokens: [String]
    /// The hint of the matched `near` entry, if any.
    public let nearHint: String?
    /// True when the response matched a `near` entry (step 1).
    public let matchedNear: Bool

    init(
        outcome: AttemptOutcome, alignment: TypedAnswerGrader.Scored?, responseTokens: [String], nearHint: String?,
        matchedNear: Bool
    ) {
        self.outcome = outcome
        self.expansion = alignment?.expansion
        self.steps = alignment?.steps ?? []
        self.responseTokens = responseTokens
        self.nearHint = nearHint
        self.matchedNear = matchedNear
    }

    private var differing: [Step] { steps.filter { $0.mark != .equal && $0.mark != .slot } }

    /// Indices into the expansion's tokens that differ from the response (accent, typo, substitution, missing):
    /// what the correction underlines.
    public var mismatches: [Int] { differing.compactMap(\.expected) }

    /// Indices into the response tokens that differ (accent, typo, substitution, extra): what the learner's
    /// answer underlines.
    public var responseMismatches: [Int] { differing.flatMap { $0.response.map(Array.init) ?? [] } }

    /// The kind of the first mismatch (for the generic hint).
    public var hintKind: HintKind? { differing.first?.hintKind }

    /// The model answer of the best expansion with the learner's own words in its slots, for "show the
    /// correction" (normalised text).
    public var correction: String? {
        guard let expansion else { return nil }
        var words = expansion.tokens
        for step in steps where step.mark == .slot {
            if let e = step.expected, let r = step.response {
                words[e] = responseTokens[r].joined(separator: " ")
            }
        }
        return words.joined(separator: " ")
    }

    /// The grade in the form the `FeedbackMachine` takes.
    public var answer: GradedAnswer {
        GradedAnswer(outcome: outcome, hintKind: hintKind, nearHint: nearHint, mismatches: mismatches)
    }
}
