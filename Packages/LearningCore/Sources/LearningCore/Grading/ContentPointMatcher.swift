import Foundation

/// Content points for talk and writing (docs/05 § Other graders): a point is found when any expansion of its
/// patterns occurs as a contiguous token sequence in the normalised response, ignoring accents. The task passes
/// when at least `pass` points are found. Digits, prices and times are spelled out first, as for transcripts.
public struct ContentPointMatcher: Sendable {
    /// One content point (`points` in a talk or writing exercise; docs/06).
    public struct Point: Sendable, Hashable {
        public let id: String
        public let accept: [AnswerPattern]

        public init(id: String, accept: [AnswerPattern]) {
            self.id = id
            self.accept = accept
        }

        public init(id: String, accept: [String]) throws(PatternError) {
            var patterns: [AnswerPattern] = []
            for source in accept { patterns.append(try AnswerPattern(source)) }
            self.init(id: id, accept: patterns)
        }
    }

    public struct Result: Sendable, Hashable {
        /// IDs of the points found, in the order given.
        public let found: [String]
        /// IDs of the points not found, in the order given.
        public let missing: [String]
        /// How many points must be found (`pass`).
        public let required: Int

        public var passed: Bool { found.count >= required }
        /// `found / required`, capped at 1 (check scoring: `score × found/required`; docs/05).
        public var fraction: Double { required <= 0 ? 1 : min(1, Double(found.count) / Double(required)) }
    }

    public let profile: LearnerProfile

    public init(profile: LearnerProfile = .unspecified) {
        self.profile = profile
    }

    public func match(response: String, points: [Point], pass: Int) -> Result {
        let tokens = Normalizer.tokens(ItalianNumbers.spellOut(response)).map(Normalizer.stripAccents)
        var found: [String] = []
        var missing: [String] = []
        for point in points {
            let expansions = point.accept.flatMap { $0.expansions(profile: profile) }.filter {
                profile.accepts($0.gender)
            }
            if expansions.contains(where: { Self.occurs($0, in: tokens) }) {
                found.append(point.id)
            } else {
                missing.append(point.id)
            }
        }
        return Result(found: found, missing: missing, required: pass)
    }

    /// Whether `expansion` occurs contiguously in `tokens` (already accent-stripped).
    static func occurs(_ expansion: PatternExpansion, in tokens: [String]) -> Bool {
        let expected = expansion.tokens.map(Normalizer.stripAccents)
        let slots = Dictionary(expansion.slots.map { ($0.tokenIndex, $0.slot) }, uniquingKeysWith: { a, _ in a })
        func matches(_ i: Int, _ j: Int) -> Bool {
            if i == expected.count { return true }
            if let slot = slots[i] {
                for k in slot.wordRange where k > 0 && j + k <= tokens.count && slot.accepts(tokens[j..<(j + k)]) {
                    if matches(i + 1, j + k) { return true }
                }
                return false
            }
            return j < tokens.count && tokens[j] == expected[i] && matches(i + 1, j + 1)
        }
        if expected.isEmpty { return true }
        return tokens.indices.contains { matches(0, $0) }
    }
}

/// The writing extras (docs/05 § Other graders, docs/06 § Guided writing): the word count, and spelling
/// suggestions for tokens that aren't known forms but are one edit from one ("Did you mean famiglia?").
/// Suggestions are advice and never fail the task.
public enum WritingChecker {
    public struct Suggestion: Sendable, Hashable {
        /// Index into the normalised tokens of the text.
        public let tokenIndex: Int
        public let token: String
        /// The known form to suggest (the first in sort order when several are one edit away).
        public let suggestion: String

        public var message: String { "Did you mean \(suggestion)?" }
    }

    /// Words in the text: its normalised tokens that contain a letter or a digit.
    public static func wordCount(_ text: String) -> Int {
        Normalizer.tokens(text).filter { $0.contains { $0.isLetter || $0.isNumber } }.count
    }

    /// Suggestions for tokens that are not known forms but are one edit from a known form. Tokens with digits
    /// are skipped.
    public static func spellingSuggestions(_ text: String, knownForms: KnownForms) -> [Suggestion] {
        Normalizer.tokens(text).enumerated().compactMap { index, token in
            guard !token.contains(where: \.isNumber), !knownForms.contains(token),
                let first = knownForms.suggestions(for: token).first
            else { return nil }
            return Suggestion(tokenIndex: index, token: token, suggestion: first)
        }
    }
}
