import Foundation

/// Matches speech transcripts against accepted patterns (docs/05 § Speech transcripts;
/// `fixtures/grading/transcripts.json`).
///
/// 1. Digits, prices and times in the raw transcript become Italian words (`ItalianNumbers.spellOutReadings`: an
///    `H.MM` that may be a price or a time is tried both ways; a `1` before a word matches *un*/*uno*/*una*/*un'*).
/// 2. The transcript and every expansion are normalised; then each standalone single letter of the transcript becomes
///    its Italian name (`letterNames`, from the pack's letter items: *M A R C O* reads *emme a erre ci o*; CL25).
/// 3. Tokens are compared without accents and with double consonants collapsed (ASR can't be trusted on length).
/// 4. Pass = every focus token heard and at least 80% of content tokens heard. Content tokens are all tokens
///    except `functionWords`; extra words in the transcript don't count against the learner. A pattern that spells
///    (`AnswerPattern.spelling`, CL40) is right only letter for letter: its letters are content tokens that must all be
///    heard, each run of them as a run of letter names that reads exactly as those letters (`LetterReader`), with no
///    letter missing or added; its other words follow the 80% rule.
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
    /// Spoken spelling: the pack's letter names, which replace single letters in a transcript (docs/05 § Speech
    /// transcripts, step 2). `.empty` matches transcripts as they are.
    public let letterNames: LetterNames

    public init(profile: LearnerProfile = .unspecified, letterNames: LetterNames = .empty) {
        self.profile = profile
        self.letterNames = letterNames
    }

    /// The outcome of matching transcripts against accepted patterns.
    public struct Match: Sendable, Hashable {
        public let passed: Bool
        /// The transcript alternative that gave this result, as recognised (for "I heard: …").
        public let heard: String
        /// Its index among the alternatives.
        public let transcriptIndex: Int
        /// The transcript after number conversion, normalisation and spelled letters (`m` → `emme`).
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

        /// The answer for the `FeedbackMachine`: a pass is `correct`, a fail `wrong`. A miss has no hint kind: the
        /// learner may have said something else rather than left a word out, so the feedback shows "I heard: …"
        /// (`heard`) with the exercise's hint, never "Something's missing." (docs/05 § Speech transcripts 6).
        public var answer: GradedAnswer {
            GradedAnswer(outcome: passed ? .correct : .wrong, hintKind: nil, mismatches: missing)
        }
    }

    /// Matches every transcript alternative (best first, as the recogniser returns them) against the accepted
    /// patterns and returns the best result; nil when there are no transcripts or no expansions.
    public func match(transcripts: [String], accepted: [AnswerPattern]) -> Match? {
        var expansions: [(expansion: PatternExpansion, spelled: (LetterReader, [LetterReader.Run])?)] = []
        for pattern in accepted {
            let reader = LetterReader(spelling: pattern.spelling, letters: letterNames)
            for expansion in pattern.expansions(profile: profile) where profile.accepts(expansion.gender) {
                let runs = reader?.runs(expansion.tokens) ?? []
                expansions.append((expansion, reader.flatMap { runs.isEmpty ? nil : ($0, runs) }))
            }
        }
        var best: Match?
        for (index, transcript) in transcripts.enumerated() {
            for reading in ItalianNumbers.spellOutReadings(transcript) {
                let (tokens, spelled) = letterNames.marking(Normalizer.tokens(reading))
                for (expansion, spelling) in expansions {
                    let result =
                        if let (reader, runs) = spelling {
                            scoreSpelled(
                                tokens, spelled: spelled, expansion, reader: reader, runs: runs, transcript: transcript,
                                index: index)
                        } else {
                            score(tokens, expansion, transcript: transcript, index: index)
                        }
                    if let current = best, !Self.isBetter(result, than: current) { continue }
                    best = result
                }
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

    /// Weights of the alignment (a weighted longest common subsequence): it keeps the matches with the largest total
    /// weight. A focus word outweighs every other word of an expansion together and a content word every function
    /// word and slot together, so the alignment never gives up a word that decides the pass for words that don't.
    /// A slot fill weighs least of all, below a function word: a slot is a wildcard and must not take a word an
    /// expected literal matches (*vengo dagli* is not *vengo dagli {ME.country}* with *dagli* as the country). It
    /// still counts as a content token for the pass.
    static let focusWeight = 1_000_000
    static let contentWeight = 1_000
    static let functionWeight = 2
    static let slotWeight = 1

    /// The comparison key: no accents, double consonants collapsed.
    static func key(_ token: String) -> String {
        EditDistance.collapseDoubleConsonants(Normalizer.stripAccents(token))
    }

    /// - Parameter skipping: expected tokens left to another rule (a spelled pattern's letters): they are never
    ///   aligned and don't count as content.
    func score(
        _ heard: [String], _ expansion: PatternExpansion, transcript: String, index: Int, skipping: Set<Int> = []
    ) -> Match {
        let expected = expansion.tokens
        let n = expected.count
        let m = heard.count
        let heardKeys = heard.map(Self.key)
        let expectedKeys = expected.map(Self.key)
        let slots = Dictionary(expansion.slots.map { ($0.tokenIndex, $0.slot) }, uniquingKeysWith: { a, _ in a })
        func isContent(_ i: Int) -> Bool {
            !skipping.contains(i) && (slots[i] != nil || !Self.functionWords.contains(expected[i]))
        }
        func weight(_ i: Int) -> Int {
            if expansion.isFocus(i) { return Self.focusWeight }
            if slots[i] != nil { return Self.slotWeight }
            return Self.functionWords.contains(expected[i]) ? Self.functionWeight : Self.contentWeight
        }

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
                    if skipping.contains(i) {
                        // left to another rule: never aligned here
                    } else if let slot = slots[i] {
                        for k in slot.wordRange where k > 0 && j + k <= m && slot.accepts(heard[j..<(j + k)]) {
                            relax((i + 1) * width + j + k, value + weight(i), from: here, matched: i)
                        }
                    } else if j < m, ItalianNumbers.matchesSpoken(expected: expectedKeys[i], heard: heardKeys[j]) {
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

    /// A spelled expansion (CL40): every run of letters must be heard, in order, as a run of letter names that reads
    /// exactly as those letters with no letter next to it (`LetterReader.span`); its other tokens are scored as usual
    /// (80% of their content tokens). Letters count as content tokens, never as function words.
    func scoreSpelled(
        _ heard: [String], spelled: Set<Int>, _ expansion: PatternExpansion, reader: LetterReader,
        runs: [LetterReader.Run], transcript: String, index: Int
    ) -> Match {
        let letters = Set(runs.flatMap { Array($0.tokens) })
        let words = score(heard, expansion, transcript: transcript, index: index, skipping: letters)
        var found = Set(words.found)
        var from = 0
        var everyRun = true
        for run in runs {
            if let span = reader.span(of: run.letters, in: heard, spelled: spelled, from: from) {
                found.formUnion(run.tokens)
                from = span.upperBound
            } else {
                everyRun = false
            }
        }
        let missing = expansion.tokens.indices.filter { !found.contains($0) }
        let missingFocus = expansion.focus.filter { !found.contains($0) }
        let lettersHeard = letters.filter(found.contains).count
        let wordsEnough =
            words.contentTotal == 0
            || Double(words.contentHeard) >= Self.contentThreshold * Double(words.contentTotal) - 1e-9
        return Match(
            passed: everyRun && missingFocus.isEmpty && wordsEnough, heard: words.heard, transcriptIndex: index,
            heardTokens: heard, expansion: expansion, found: found.sorted(), missing: missing,
            missingFocus: missingFocus, contentHeard: words.contentHeard + lettersHeard,
            contentTotal: words.contentTotal + letters.count)
    }
}
