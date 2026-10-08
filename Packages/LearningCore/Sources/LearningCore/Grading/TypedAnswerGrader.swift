import Foundation

/// Grades a typed answer against accepted patterns (docs/05 § Typed answers): cloze, recall, generated cards and
/// typed conversation turns. `fixtures/grading/typed-answers.json` is the reference.
///
/// 1. A response equal to a `near` expansion returns that entry's outcome (default `wrong`) and hint.
/// 2. Otherwise the response tokens are aligned with every accepted expansion (token-level edit distance: equal 0;
///    accent-only 0.1 except accent-sensitive words; typo 0.5 = Damerau-Levenshtein 1 on a non-focus token of
///    ≥ 4 letters that is not another form of the same item; substitution, insertion, deletion 1). The cheapest
///    expansion wins. A response token that is another form of the expected token's item is an inflection error:
///    a substitution with hint kind `ending`, never a typo. The other gender's form of a `{m:…|f:…}` group (or of a
///    gendered `{ME.nationality}`) counts as another form of the same item. On an accent-sensitive word only the
///    presence of the accent makes another word (*e* for *è*); the wrong accent (*é* for *è*) is an accent slip
///    that costs like a typo (0.5, `almost`).
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
        let expansions = accepted.flatMap { $0.expansions(profile: profile) }.filter { profile.accepts($0.gender) }
        var genderPairs = Set<FormPair>()
        for pattern in accepted { genderPairs.formUnion(pattern.genderFormPairs(profile: profile)) }
        var session = Session(grader: self, response: response, genderPairs: genderPairs)
        let best = session.bestAlignment(expansions)

        for entry in near {
            let matches = entry.pattern.expansions(profile: profile).contains { session.isExactMatch($0) }
            if matches {
                return TypedGrade(
                    outcome: entry.outcome, alignment: best, response: session.response, nearHint: entry.hint,
                    matchedNear: true)
            }
        }
        guard let best else {
            return TypedGrade(
                outcome: .wrong, alignment: nil, response: session.response, nearHint: nil, matchedNear: false)
        }
        return TypedGrade(
            outcome: best.outcome, alignment: best, response: session.response, nearHint: nil, matchedNear: false)
    }

    // MARK: - Alignment

    /// The response, normalised once per grade: tokens, the learner's own spelling of each (for corrections) and
    /// the accent-stripped forms the cost rules compare.
    struct Response {
        let tokens: [String]
        let display: [String]
        let stripped: [String]

        init(_ text: String) {
            tokens = Normalizer.tokens(text)
            let display = Normalizer.displayTokens(text)
            self.display = display.count == tokens.count ? display : tokens
            stripped = tokens.map(Normalizer.stripAccents)
        }
    }

    struct Scored {
        var expansion: PatternExpansion
        var cost: TokenAligner.Cost
        var steps: [TypedGrade.Step]

        var outcome: AttemptOutcome {
            if steps.contains(where: \.mark.isHard) { return .wrong }
            if steps.allSatisfy({ $0.mark == .equal || $0.mark == .slot }) { return .correct }
            return steps.contains(where: { $0.mark == .typo || $0.almost }) ? .almost : .correctWithNote
        }
    }

    /// One grade's working state. Pairings depend only on the expected token, whether it is focus, and the
    /// response token, so they are computed once per distinct expected token and reused across expansions
    /// (a 512-expansion pattern shares a few dozen tokens): docs/02's 50 ms Check → feedback budget.
    struct Session {
        let grader: TypedAnswerGrader
        let response: Response
        let genderPairs: Set<FormPair>
        private var rows: [RowKey: [TokenAligner.Pairing<TypedGrade.Mark>]] = [:]

        struct RowKey: Hashable {
            let token: String
            let focus: Bool
        }

        init(grader: TypedAnswerGrader, response: String, genderPairs: Set<FormPair>) {
            self.grader = grader
            self.response = Response(response)
            self.genderPairs = genderPairs
        }

        /// The cheapest expansion (docs/05 § Typed answers 2); on a tie, the one with fewer hard operations, then
        /// more exact pairs, then the earlier one (`TokenAligner.Cost` orders them).
        mutating func bestAlignment(_ expansions: [PatternExpansion]) -> Scored? {
            var best: (expansion: PatternExpansion, cost: TokenAligner.Cost, ops: [Op])?
            let m = response.tokens.count
            for expansion in expansions {
                if let current = best {
                    // Every response token beyond what the expansion can take, and every expected word or slot it
                    // can't cover, costs at least one insertion or deletion.
                    let (low, high) = Self.lengthRange(expansion)
                    let gap = max(0, m - high, low - m)
                    if gap * TypedAnswerGrader.indel > current.cost.total { continue }
                }
                let (cost, ops) = align(expansion)
                if let current = best, !(cost < current.cost) { continue }
                best = (expansion, cost, ops)
                // Nothing beats an exact pairing of every response token.
                if cost.total == 0, cost.hard == 0, cost.exact == m { break }
            }
            return best.map { Scored(expansion: $0.expansion, cost: $0.cost, steps: steps($0.expansion, $0.ops)) }
        }

        /// A response equals an expansion when every word token is identical and every slot is filled (step 1).
        mutating func isExactMatch(_ expansion: PatternExpansion) -> Bool {
            align(expansion).ops.allSatisfy { op in
                switch op {
                case .pair(_, _, let mark): mark == .equal
                case .slot: true
                case .delete, .insert: false
                }
            }
        }

        typealias Op = TokenAligner.Op<TypedGrade.Mark>

        /// How many response tokens the expansion covers at no cost: its words plus each slot's word range.
        static func lengthRange(_ expansion: PatternExpansion) -> (Int, Int) {
            var low = expansion.tokens.count - expansion.slots.count
            var high = low
            for position in expansion.slots {
                low += position.slot.wordRange.lowerBound
                high += position.slot.wordRange.upperBound
            }
            return (low, high)
        }

        mutating func align(_ expansion: PatternExpansion) -> (cost: TokenAligner.Cost, ops: [Op]) {
            let expected = expansion.tokens
            let slots = Dictionary(expansion.slots.map { ($0.tokenIndex, $0.slot) }, uniquingKeysWith: { a, _ in a })
            let table = expected.indices.map { i in
                slots[i] == nil ? row(expected[i], focus: expansion.isFocus(i)) : []
            }
            let tokens = response.tokens
            return TokenAligner.align(
                expectedCount: expected.count, responseCount: tokens.count, indel: TypedAnswerGrader.indel,
                slotRange: { slots[$0]?.wordRange },
                slotAccepts: { i, range in slots[i]?.accepts(tokens[range]) ?? false },
                pair: { i, j in table[i][j] })
        }

        /// The pairings of one expected token with every response token.
        private mutating func row(_ token: String, focus: Bool) -> [TokenAligner.Pairing<TypedGrade.Mark>] {
            let key = RowKey(token: token, focus: focus)
            if let cached = rows[key] { return cached }
            let stripped = Normalizer.stripAccents(token)
            let row = response.tokens.indices.map { j in
                pairing(expected: token, strippedExpected: stripped, response: j, focus: focus)
            }
            rows[key] = row
            return row
        }

        func isSameItem(_ e: String, _ r: String) -> Bool {
            grader.knownForms.areFormsOfSameItem(e, r) || genderPairs.contains(FormPair(e, r))
        }

        /// docs/05 § Typed answers 2: the cost of pairing one expected token with one response token.
        func pairing(
            expected e: String, strippedExpected se: String, response j: Int, focus: Bool
        ) -> TokenAligner.Pairing<TypedGrade.Mark> {
            let r = response.tokens[j]
            if e == r { return .init(mark: .equal, cost: 0, hard: false) }
            let sr = response.stripped[j]
            let sameItem = isSameItem(e, r)
            if se == sr, !sameItem, !Normalizer.isOtherAccentSensitiveWord(e, r) {
                // On an accent-sensitive word the wrong accent (é for è) is a slip on the very thing that tells the
                // words apart: `almost`, at a typo's cost. A missing or added accent there is another word (above).
                let sensitive = Normalizer.isAccentSensitive(e) || Normalizer.isAccentSensitive(r)
                return .init(mark: .accent, cost: sensitive ? 5 : 1, hard: false)
            }
            if !focus, !sameItem, se.count >= 4, EditDistance.isOneEdit(se, sr) {
                return .init(mark: .typo, cost: 5, hard: false)
            }
            return .init(mark: .substitution, cost: 10, hard: true)
        }

        func steps(_ expansion: PatternExpansion, _ ops: [Op]) -> [TypedGrade.Step] {
            let expected = expansion.tokens
            return ops.map { op -> TypedGrade.Step in
                switch op {
                case .pair(let e, let r, let mark):
                    let sensitive =
                        Normalizer.isAccentSensitive(expected[e]) || Normalizer.isAccentSensitive(response.tokens[r])
                    let almost = mark == .accent && sensitive
                    return TypedGrade.Step(
                        mark: mark, expected: e, response: r..<(r + 1),
                        hintKind: hintKind(for: mark, expected: expected[e], response: response.tokens[r]),
                        almost: almost)
                case .slot(let e, let r):
                    return TypedGrade.Step(mark: .slot, expected: e, response: r, hintKind: nil)
                case .delete(let e):
                    return TypedGrade.Step(mark: .deletion, expected: e, response: nil, hintKind: .missing)
                case .insert(let r):
                    return TypedGrade.Step(mark: .insertion, expected: nil, response: r..<(r + 1), hintKind: .extra)
                }
            }
        }

        func hintKind(for mark: TypedGrade.Mark, expected: String, response: String) -> HintKind? {
            switch mark {
            case .equal, .slot: return nil
            case .accent, .typo: return .spelling
            case .deletion: return .missing
            case .insertion: return .extra
            case .substitution:
                if isSameItem(expected, response) { return .ending }
                if grader.knownForms.contains(response) { return .realWord }
                return .spelling
            }
        }
    }

    /// The cost of an insertion or a deletion, in tenths.
    static let indel = 10
}

/// The result of grading a typed answer.
public struct TypedGrade: Sendable, Hashable {
    /// How one expected token compares with the response.
    public enum Mark: String, Sendable, Hashable {
        case equal, accent, typo, substitution, deletion, insertion
        /// A slot (`{NAME}`, `{NUMBER}` …) filled by response tokens.
        case slot

        /// A substitution, a missing or an extra word: these make an answer `wrong`.
        var isHard: Bool { self == .substitution || self == .deletion || self == .insertion }
    }

    /// One step of the alignment, in reading order.
    public struct Step: Sendable, Hashable {
        public let mark: Mark
        /// Index into the expansion's tokens (nil for an inserted response token).
        public let expected: Int?
        /// Indices into the response tokens (nil for a missing expected token).
        public let response: Range<Int>?
        public let hintKind: HintKind?
        /// An accent slip that makes the answer `almost` rather than `correctWithNote`: the wrong accent on an
        /// accent-sensitive word (*é* for *è*).
        let almost: Bool

        init(mark: Mark, expected: Int?, response: Range<Int>?, hintKind: HintKind?, almost: Bool = false) {
            self.mark = mark
            self.expected = expected
            self.response = response
            self.hintKind = hintKind
            self.almost = almost
        }
    }

    /// `correct`, `correctWithNote`, `almost` or `wrong`.
    public let outcome: AttemptOutcome
    /// The accepted expansion the response came closest to (nil when nothing is accepted).
    public let expansion: PatternExpansion?
    /// The alignment with `expansion`.
    public let steps: [Step]
    /// The normalised response tokens.
    public let responseTokens: [String]
    /// The response tokens as the learner wrote them (case kept), one per normalised token.
    let responseDisplayTokens: [String]
    /// The hint of the matched `near` entry, if any.
    public let nearHint: String?
    /// True when the response matched a `near` entry (step 1).
    public let matchedNear: Bool

    init(
        outcome: AttemptOutcome, alignment: TypedAnswerGrader.Scored?, response: TypedAnswerGrader.Response,
        nearHint: String?, matchedNear: Bool
    ) {
        self.outcome = outcome
        self.expansion = alignment?.expansion
        self.steps = alignment?.steps ?? []
        self.responseTokens = response.tokens
        self.responseDisplayTokens = response.display
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

    /// The kind of the mismatch the generic hint is about: the first substitution, missing or extra word when
    /// there is one (that is what makes the answer wrong; an accent slip before it is only a note), else the
    /// first mismatch.
    public var hintKind: HintKind? { (differing.first { $0.mark.isHard } ?? differing.first)?.hintKind }

    /// The model answer of the best expansion, in the author's case and punctuation, with the learner's own
    /// words in its slots (as they wrote them), for "show the correction": `Mi chiamo Anna Maria.`, `E Lei?`. A slot
    /// the response left empty keeps its placeholder.
    public var correction: String? {
        guard let expansion else { return nil }
        var fills: [Int: String] = [:]
        for step in steps where step.mark == .slot {
            if let e = step.expected, let r = step.response {
                fills[e] = responseDisplayTokens[r].joined(separator: " ")
            }
        }
        return expansion.rawFilled { fills[expansion.slots[$0].tokenIndex] }
    }

    /// The grade in the form the `FeedbackMachine` takes.
    public var answer: GradedAnswer {
        GradedAnswer(outcome: outcome, hintKind: hintKind, nearHint: nearHint, mismatches: mismatches)
    }
}
