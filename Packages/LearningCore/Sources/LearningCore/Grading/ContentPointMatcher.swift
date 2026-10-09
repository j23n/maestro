import Foundation

/// Content points for talk and writing (docs/05 § Other graders): a point is found when any expansion of its
/// patterns occurs as a contiguous token sequence in the normalised response, ignoring accents, and for a spoken
/// response (talk) also consonant length, as for transcripts (ASR can't be trusted on it). The task passes when at
/// least `pass` points are found. Digits, prices and times are spelled out first, as for transcripts (every
/// reading of an ambiguous `H.MM` is tried; a `1` before a word stands for *un*/*uno*/*una*/*un'*), and in a spoken
/// response single letters become their Italian names (`letterNames`: *M A R C O* reads *emme a erre ci o*; CL25),
/// and a point that spells is matched letter for letter (CL40, `occursSpelled`).
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
    /// Spoken spelling: the pack's letter names, which replace single letters in a spoken response (docs/05 § Speech
    /// transcripts, step 2). Typed responses are never mapped.
    public let letterNames: LetterNames

    public init(profile: LearnerProfile = .unspecified, letterNames: LetterNames = .empty) {
        self.profile = profile
        self.letterNames = letterNames
    }

    /// - Parameter spoken: the response is a speech transcript (talk spoken), so double consonants are collapsed on
    ///   both sides before comparing and spelled letters become their names.
    public func match(response: String, points: [Point], pass: Int, spoken: Bool = false) -> Result {
        let readings = ItalianNumbers.spellOutReadings(response).map { reading in
            let normalised = Normalizer.tokens(reading)
            let tokens = spoken ? letterNames.apply(normalised) : normalised
            return (tokens: tokens, keys: tokens.map { Self.key($0, spoken: spoken) })
        }
        var found: [String] = []
        var missing: [String] = []
        for point in points {
            let isFound = point.accept.contains { pattern in
                // A point that spells is matched letter for letter in speech (CL40); typed answers as written.
                let reader = spoken ? LetterReader(spelling: pattern.spelling, letters: letterNames) : nil
                return pattern.expansions(profile: profile).contains { expansion in
                    guard profile.accepts(expansion.gender) else { return false }
                    if let reader, case let runs = reader.runs(expansion.tokens), !runs.isEmpty {
                        return readings.contains {
                            Self.occursSpelled(expansion, runs: runs, reader: reader, in: $0.tokens, keys: $0.keys)
                        }
                    }
                    return readings.contains { Self.occurs(expansion, in: $0.tokens, keys: $0.keys, spoken: spoken) }
                }
            }
            if isFound {
                found.append(point.id)
            } else {
                missing.append(point.id)
            }
        }
        return Result(found: found, missing: missing, required: pass)
    }

    /// The comparison key: no accents; for speech, double consonants collapsed too.
    static func key(_ token: String, spoken: Bool) -> String {
        let stripped = Normalizer.stripAccents(token)
        return spoken ? EditDistance.collapseDoubleConsonants(stripped) : stripped
    }

    /// Whether `expansion` occurs contiguously in `tokens` (normalised; `keys` are their `key(_:spoken:)`): words
    /// compare by key, and a slot takes the tokens themselves (`{NUMBER}` reads *diciassette*, not its key).
    static func occurs(_ expansion: PatternExpansion, in tokens: [String], keys: [String], spoken: Bool) -> Bool {
        let expected = expansion.tokens.map { key($0, spoken: spoken) }
        let slots = Dictionary(expansion.slots.map { ($0.tokenIndex, $0.slot) }, uniquingKeysWith: { a, _ in a })
        func matches(_ i: Int, _ j: Int) -> Bool {
            if i == expected.count { return true }
            if let slot = slots[i] {
                for k in slot.wordRange where k > 0 && j + k <= tokens.count && slot.accepts(tokens[j..<(j + k)]) {
                    if matches(i + 1, j + k) { return true }
                }
                return false
            }
            return j < tokens.count && ItalianNumbers.matchesSpoken(expected: expected[i], heard: keys[j])
                && matches(i + 1, j + 1)
        }
        if expected.isEmpty { return true }
        return tokens.indices.contains { matches(0, $0) }
    }
}

extension ContentPointMatcher {
    /// `occurs` for a spoken expansion that spells (CL40): its runs of letters must occur as letter names that read as
    /// exactly those letters (`LetterReader.ends`: *esse esse* and *doppia esse* both read SS), its other tokens as
    /// usual, all contiguous.
    static func occursSpelled(
        _ expansion: PatternExpansion, runs: [LetterReader.Run], reader: LetterReader, in tokens: [String],
        keys: [String]
    ) -> Bool {
        enum Segment {
            case word(Int)
            case run([Character])
        }
        let runAt = Dictionary(runs.map { ($0.tokens.lowerBound, $0) }, uniquingKeysWith: { a, _ in a })
        var segments: [Segment] = []
        var i = 0
        while i < expansion.tokens.count {
            if let run = runAt[i] {
                segments.append(.run(run.letters))
                i = run.tokens.upperBound
            } else {
                segments.append(.word(i))
                i += 1
            }
        }
        let expected = expansion.tokens.map { key($0, spoken: true) }
        let slots = Dictionary(expansion.slots.map { ($0.tokenIndex, $0.slot) }, uniquingKeysWith: { a, _ in a })
        func matches(_ k: Int, _ j: Int) -> Bool {
            guard k < segments.count else { return true }
            switch segments[k] {
            case .run(let letters):
                return reader.ends(keys, from: j, reading: letters[...]).contains { matches(k + 1, $0) }
            case .word(let i):
                if let slot = slots[i] {
                    for n in slot.wordRange where n > 0 && j + n <= tokens.count && slot.accepts(tokens[j..<(j + n)]) {
                        if matches(k + 1, j + n) { return true }
                    }
                    return false
                }
                return j < tokens.count && ItalianNumbers.matchesSpoken(expected: expected[i], heard: keys[j])
                    && matches(k + 1, j + 1)
            }
        }
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
