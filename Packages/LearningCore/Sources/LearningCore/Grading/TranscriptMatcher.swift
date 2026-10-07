import Foundation

/// Matches speech transcripts against accepted patterns (docs/05 § Speech transcripts;
/// `fixtures/grading/transcripts.json`).
///
/// 1. Digits, prices and times in the raw transcript become Italian words (`ItalianNumbers.spellOut`).
/// 2. The transcript and every expansion are normalised.
/// 3. Tokens are compared without accents and with double consonants collapsed (ASR can't be trusted on length).
/// 4. Pass = every focus token heard and at least 80% of content tokens heard. Content tokens are all tokens
///    except `functionWords`; extra words in the transcript don't count against the learner.
/// 5. The best result across transcript alternatives (and expansions) wins.
/// Feedback says "I heard: …" (`heard`); it never claims to judge pronunciation.
public struct TranscriptMatcher: Sendable {
    /// Articles, simple and articulated prepositions, clitics, e/o/ma. Normative: the list must equal
    /// `functionWords` in `fixtures/grading/transcripts.json` (a test checks it).
    public static let functionWordList: [String] = [
        "il", "lo", "la", "l'", "i", "gli", "le", "un", "uno", "una", "un'",
        "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
        "al", "allo", "alla", "all'", "ai", "agli", "alle",
        "del", "dello", "della", "dell'", "dei", "degli", "delle",
        "nel", "nello", "nella", "nell'", "nei", "negli", "nelle",
        "dal", "dallo", "dalla", "dall'", "dai", "dagli", "dalle",
        "sul", "sullo", "sulla", "sull'", "sui", "sugli", "sulle",
        "mi", "ti", "si", "ci", "vi", "ne", "li",
        "e", "o", "ma",
    ]
    public static let functionWords = Set(functionWordList)

    /// The share of content tokens that must be heard (docs/05: 80%).
    public static let contentThreshold = 0.8

    public let profile: LearnerProfile

    public init(profile: LearnerProfile = .unspecified) {
        self.profile = profile
    }

    /// The outcome of matching transcripts against accepted patterns.
    public struct Match: Sendable, Hashable {
        public let passed: Bool
        /// The transcript alternative that gave this result, as recognised (for "I heard: …").
        public let heard: String
        /// Its index among the alternatives.
        public let transcriptIndex: Int
        /// The transcript after number conversion and normalisation.
        public let heardTokens: [String]
        /// The accepted expansion it was compared with.
        public let expansion: PatternExpansion
        /// Indices into the expansion's tokens that were heard.
        public let found: [Int]
        /// Indices into the expansion's tokens that were not heard.
        public let missing: [Int]
        /// Focus tokens that were not heard (any one fails the match).
        public let missingFocus: [Int]
        public let contentHeard: Int
        public let contentTotal: Int

        /// Expected words found, in order (for showing which words were heard).
        public var foundWords: [String] { found.map { expansion.tokens[$0] } }

        /// The answer for the `FeedbackMachine`: a pass is `correct`, a fail `wrong`.
        public var answer: GradedAnswer {
            GradedAnswer(
                outcome: passed ? .correct : .wrong, hintKind: missing.isEmpty ? nil : .missing, mismatches: missing)
        }
    }

    /// Matches every transcript alternative (best first, as the recogniser returns them) against the accepted
    /// patterns and returns the best result; nil when there are no transcripts or no expansions.
    public func match(transcripts: [String], accepted: [AnswerPattern]) -> Match? {
        let expansions = accepted.flatMap { $0.expansions(profile: profile) }.filter { profile.accepts($0.gender) }
        var best: Match?
        for (index, transcript) in transcripts.enumerated() {
            let tokens = Normalizer.tokens(ItalianNumbers.spellOut(transcript))
            for expansion in expansions {
                let result = score(tokens, expansion, transcript: transcript, index: index)
                if let current = best, !Self.isBetter(result, than: current) { continue }
                best = result
            }
        }
        return best
    }

    /// Single-transcript convenience.
    public func match(transcript: String, accepted: AnswerPattern) -> Match? {
        match(transcripts: [transcript], accepted: [accepted])
    }

    static func isBetter(_ a: Match, than b: Match) -> Bool {
        if a.passed != b.passed { return a.passed }
        // Compare heard/total ratios exactly (an empty content set counts as fully heard).
        let ra = (a.contentHeard, max(a.contentTotal, 1))
        let rb = (b.contentHeard, max(b.contentTotal, 1))
        let lhs = ra.0 * rb.1
        let rhs = rb.0 * ra.1
        if lhs != rhs { return lhs > rhs }
        return a.missingFocus.count < b.missingFocus.count
    }

    /// The comparison key: no accents, double consonants collapsed.
    static func key(_ token: String) -> String {
        EditDistance.collapseDoubleConsonants(Normalizer.stripAccents(token))
    }

    func score(_ heard: [String], _ expansion: PatternExpansion, transcript: String, index: Int) -> Match {
        let expected = expansion.tokens
        let n = expected.count
        let m = heard.count
        let heardKeys = heard.map(Self.key)
        let expectedKeys = expected.map(Self.key)
        let slots = Dictionary(expansion.slots.map { ($0.tokenIndex, $0.slot) }, uniquingKeysWith: { a, _ in a })
        func isContent(_ i: Int) -> Bool { slots[i] != nil || !Self.functionWords.contains(expected[i]) }
        func weight(_ i: Int) -> Int { expansion.isFocus(i) ? 100 : (isContent(i) ? 10 : 1) }

        // Weighted longest common subsequence; a slot may take a run of transcript words.
        let width = m + 1
        var best = [Int](repeating: -1, count: (n + 1) * width)
        var back = [(from: Int, matched: Int?)?](repeating: nil, count: (n + 1) * width)
        best[0] = 0
        func relax(_ to: Int, _ value: Int, from: Int, matched: Int?) {
            if value > best[to] {
                best[to] = value
                back[to] = (from, matched)
            }
        }
        for i in 0...n {
            for j in 0...m {
                let here = i * width + j
                let value = best[here]
                guard value >= 0 else { continue }
                if i < n {
                    if let slot = slots[i] {
                        for k in slot.wordRange where k > 0 && j + k <= m && slot.accepts(heard[j..<(j + k)]) {
                            relax((i + 1) * width + j + k, value + weight(i), from: here, matched: i)
                        }
                    } else if j < m, expectedKeys[i] == heardKeys[j] {
                        relax((i + 1) * width + j + 1, value + weight(i), from: here, matched: i)
                    }
                    relax((i + 1) * width + j, value, from: here, matched: nil)
                }
                if j < m { relax(here + 1, value, from: here, matched: nil) }
            }
        }
        var found: [Int] = []
        var cell = n * width + m
        while cell != 0, let link = back[cell] {
            if let i = link.matched { found.append(i) }
            cell = link.from
        }
        found.reverse()
        let foundSet = Set(found)
        let missing = (0..<n).filter { !foundSet.contains($0) }
        let missingFocus = expansion.focus.filter { !foundSet.contains($0) }
        let content = (0..<n).filter(isContent)
        let contentHeard = content.filter { foundSet.contains($0) }.count
        let enough =
            content.isEmpty
            ? missing.isEmpty
            : Double(contentHeard) >= Self.contentThreshold * Double(content.count) - 1e-9
        return Match(
            passed: missingFocus.isEmpty && enough, heard: transcript.trimmingCharacters(in: .whitespacesAndNewlines),
            transcriptIndex: index, heardTokens: heard, expansion: expansion, found: found, missing: missing,
            missingFocus: missingFocus, contentHeard: contentHeard, contentTotal: content.count)
    }
}
