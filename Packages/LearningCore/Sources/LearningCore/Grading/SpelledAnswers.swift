import Foundation

/// One name that a spelled pattern spells with (CL40; `PatternPayload.spelling`): the pack builder lists, for each
/// pattern whose tokens resolve to letter items (or to *doppia*), the names those tokens are and the letter each one
/// names, from the annotation, so the matchers never guess from the surface whether *a* is a letter or a preposition.
public struct SpellingName: Codable, Sendable, Hashable {
    /// The name, normalised: `vi`, `i lunga`, `doppia`.
    public let name: String
    /// The letter it names (one of A–Z), or nil for the doubling word: *doppia esse* is two S.
    public let letter: String?

    public init(name: String, letter: String?) {
        self.name = name
        self.letter = letter
    }
}

/// Reads spoken letters for a spelled pattern (CL40, docs/05 § Speech transcripts): a spelling is right only letter for
/// letter. The pattern's runs of letter names are compared with the transcript as letters, so the accepted variants
/// count (*vi* and *vu* are V when the pattern lists both, *doppia esse* and *esse esse* are both SS, *doppia vu* is W
/// or VV), and a run must be heard whole, in order, with no letter missing or added.
struct LetterReader: Sendable {
    enum Unit: Hashable, Sendable {
        case letter(Character)
        /// The doubling word: the next letter twice.
        case double
    }

    /// A run of letters in an expected expansion and the tokens that spell it.
    struct Run: Hashable, Sendable {
        let letters: [Character]
        let tokens: Range<Int>
    }

    /// Name (comparison keys of its tokens) → unit: the pattern's own names, for the expected side.
    let expected: [[String]: Unit]
    /// The same plus the pack's letter names and doubling word, for the transcript.
    let heard: [[String]: Unit]
    /// The pack's names that are never an ordinary word (`LetterNames.neverWords`), as comparison keys: hearing one is
    /// hearing a letter. Every other name may be a word (a vowel, *di*, *ci*, *ti*, *vi*).
    let never: Set<[String]>
    /// The most tokens a name has.
    let longest: Int

    /// nil when the pattern spells nothing (no `spelling`, or no usable name in it).
    init?(spelling: [SpellingName]?, letters: LetterNames) {
        guard let spelling else { return nil }
        var expected: [[String]: Unit] = [:]
        for s in spelling {
            let keys = Normalizer.tokens(s.name).map(TranscriptMatcher.key)
            guard !keys.isEmpty else { continue }
            if let letter = s.letter {
                guard let key = LetterNames.key(letter), let c = key.uppercased().first else { continue }
                expected[keys] = .letter(c)
            } else {
                expected[keys] = .double
            }
        }
        guard !expected.isEmpty else { return nil }
        var heard = expected
        for (letter, name) in letters.names {
            guard let c = letter.uppercased().first else { continue }
            let keys = name.map(TranscriptMatcher.key)
            if heard[keys] == nil { heard[keys] = .letter(c) }
        }
        if let doubling = letters.doubling {
            let keys = doubling.map(TranscriptMatcher.key)
            if heard[keys] == nil { heard[keys] = .double }
        }
        self.expected = expected
        self.heard = heard
        never = Set(letters.neverWords.map { $0.map(TranscriptMatcher.key) })
        longest = heard.keys.map(\.count).max() ?? 1
    }

    /// The runs of letters in an expected expansion's tokens, reading its names longest first (as the annotator reads
    /// chunks: *doppia vu* is W when the pattern names it). A doubling word with no letter after it is a word.
    func runs(_ tokens: [String]) -> [Run] {
        let keys = tokens.map(TranscriptMatcher.key)
        var runs: [Run] = []
        var letters: [Character] = []
        var start = 0
        func close(_ end: Int) {
            if !letters.isEmpty { runs.append(Run(letters: letters, tokens: start..<end)) }
            letters = []
        }
        var i = 0
        while i < keys.count {
            guard let (length, unit) = Self.longestName(in: expected, keys, at: i, longest: longest) else {
                close(i)
                i += 1
                continue
            }
            switch unit {
            case .letter(let c):
                if letters.isEmpty { start = i }
                letters.append(c)
                i += length
            case .double:
                let after = Self.longestName(in: expected, keys, at: i + length, longest: longest)
                if case let (next, .letter(c))? = after {
                    if letters.isEmpty { start = i }
                    letters += [c, c]
                    i += length + next
                } else {
                    close(i)
                    i += length
                }
            }
        }
        close(keys.count)
        return runs
    }

    static func longestName(
        in table: [[String]: Unit], _ keys: [String], at i: Int, longest: Int
    )
        -> (Int, Unit)?
    {
        guard i < keys.count else { return nil }
        for length in stride(from: min(longest, keys.count - i), through: 1, by: -1) {
            if let unit = table[Array(keys[i..<(i + length)])] { return (length, unit) }
        }
        return nil
    }

    /// Every end `e` such that the transcript's tokens `start..<e` read as exactly `letters` (each token part of a
    /// name; a doubling word gives its next letter twice).
    func ends(_ keys: [String], from start: Int, reading letters: ArraySlice<Character>) -> [Int] {
        guard let first = letters.first else { return [start] }
        var out: [Int] = []
        for length in 1...longest where start + length <= keys.count {
            guard let unit = heard[Array(keys[start..<(start + length)])] else { continue }
            switch unit {
            case .letter(let c):
                if c == first { out += ends(keys, from: start + length, reading: letters.dropFirst()) }
            case .double:
                guard letters.dropFirst().first == first else { continue }
                let after = start + length
                for next in 1...longest where after + next <= keys.count {
                    if heard[Array(keys[after..<(after + next)])] == .letter(first) {
                        out += ends(keys, from: after + next, reading: letters.dropFirst(2))
                    }
                }
            }
        }
        return out
    }

    /// The first span from `start` on that reads as exactly `letters` with no letter right before or after it: a
    /// missing or extra letter fails the run. A neighbour that may be an ordinary word (a vowel as the recogniser wrote
    /// it, *è* included, or *di*, *ci*, *ti*: a name that isn't one of `never`) doesn't count as a letter; one the
    /// recogniser wrote as a single consonant (`spelled`), a name of two words, a doubling word or a name that is never
    /// a word does. A span never ends inside a longer name (`endsInsideName`: *elle, i* is not *elle, i lunga*).
    func span(of letters: [Character], in tokens: [String], spelled: Set<Int>, from start: Int) -> Range<Int>? {
        let keys = tokens.map(TranscriptMatcher.key)
        guard start <= keys.count else { return nil }
        for s in start..<keys.count where !letterEnds(at: s, keys, spelled) {
            for e in ends(keys, from: s, reading: letters[...]).sorted()
            where !letterStarts(at: e, keys, spelled) && !endsInsideName(s..<e, keys) {
                return s..<e
            }
        }
        return nil
    }

    /// Whether a heard name that starts inside `run` goes on past its end, so the run would end inside that name: a
    /// transcript's *elle i lunga* (L J) has no run *elle, i* (L I).
    func endsInsideName(_ run: Range<Int>, _ keys: [String]) -> Bool {
        guard longest > 1 else { return false }
        return run.contains { k in
            (2...longest).contains { length in
                k + length > run.upperBound && k + length <= keys.count && heard[Array(keys[k..<(k + length)])] != nil
            }
        }
    }

    /// Whether a name that is surely a letter ends right before `end`.
    func letterEnds(at end: Int, _ keys: [String], _ spelled: Set<Int>) -> Bool {
        for length in 1...longest where end - length >= 0 {
            let range = (end - length)..<end
            if let unit = heard[Array(keys[range])], isSure(unit, range, keys, spelled) { return true }
        }
        return false
    }

    /// Whether a name that is surely a letter starts at `start`.
    func letterStarts(at start: Int, _ keys: [String], _ spelled: Set<Int>) -> Bool {
        for length in 1...longest where start + length <= keys.count {
            let range = start..<(start + length)
            if let unit = heard[Array(keys[range])], isSure(unit, range, keys, spelled) { return true }
        }
        return false
    }

    /// A doubling word, a name of two words, a letter the recogniser wrote as one, or a name that is never an ordinary
    /// word. A one-word name that may be a word isn't: the vowels (whose names are themselves, so *è* too: keys have no
    /// accents) and the names the pack also has as words.
    private func isSure(_ unit: Unit, _ range: Range<Int>, _ keys: [String], _ spelled: Set<Int>) -> Bool {
        if unit == .double || range.count > 1 || range.contains(where: spelled.contains) { return true }
        return never.contains([keys[range.lowerBound]])
    }

    /// CL41: the runs of letter names in a response (maximal spans whose every token is part of a heard name) that hold
    /// a real spelling: a name that is never an ordinary word (`never`) or a letter the recogniser wrote as one
    /// (`spelled`). A spell point is found only inside one, so *e ci vediamo* and *e a presto* spell nothing, while
    /// *emme, i, a* and *M A R C O* do.
    func spellings(in tokens: [String], spelled: Set<Int>) -> [Range<Int>] {
        let keys = tokens.map(TranscriptMatcher.key)
        var covered = [Bool](repeating: false, count: keys.count)
        var sure = spelled
        for k in keys.indices {
            for length in 1...longest where k + length <= keys.count {
                let name = Array(keys[k..<(k + length)])
                guard heard[name] != nil else { continue }
                for t in k..<(k + length) { covered[t] = true }
                if never.contains(name) { sure.insert(k) }
            }
        }
        var runs: [Range<Int>] = []
        var k = 0
        while k < keys.count {
            guard covered[k] else {
                k += 1
                continue
            }
            var end = k
            while end < keys.count && covered[end] { end += 1 }
            if (k..<end).contains(where: sure.contains) { runs.append(k..<end) }
            k = end
        }
        return runs
    }
}
