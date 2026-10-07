import Foundation

/// Character-level distance helpers shared by the graders (docs/05 § Grading).
public enum EditDistance {
    /// True when the Damerau-Levenshtein distance between `a` and `b` is exactly 1: one substitution, insertion,
    /// deletion or transposition of two adjacent characters (`cappuccnio` → `cappuccino`).
    public static func isOneEdit(_ a: String, _ b: String) -> Bool {
        isOneEdit(Array(a), Array(b))
    }

    static func isOneEdit(_ a: [Character], _ b: [Character]) -> Bool {
        if a.count == b.count {
            let diffs = a.indices.filter { a[$0] != b[$0] }
            if diffs.count == 1 { return true }
            if diffs.count == 2, diffs[1] == diffs[0] + 1 {
                return a[diffs[0]] == b[diffs[1]] && a[diffs[1]] == b[diffs[0]]
            }
            return false
        }
        let (short, long) = a.count < b.count ? (a, b) : (b, a)
        guard long.count == short.count + 1 else { return false }
        var i = 0
        while i < short.count, short[i] == long[i] { i += 1 }
        return short[i...].elementsEqual(long[(i + 1)...])
    }

    /// Italian consonants for the double-consonant rules (after `Normalizer.stripAccents`).
    static let consonants: Set<Character> = Set("bcdfghjklmnpqrstvwxyz")

    /// Collapses every run of one repeated consonant to a single letter: `cappuccino` → `capucino`, `ecco` → `eco`.
    public static func collapseDoubleConsonants(_ text: String) -> String {
        var out = ""
        var previous: Character?
        for c in text {
            if c == previous, consonants.contains(c) { continue }
            out.append(c)
            previous = c
        }
        return out
    }

    /// Where two words differ only in consonant length, the first such consonant and whether `target` has it
    /// doubled (`cornetto` vs `corneto` → `t`, true). Nil unless the words differ only in consonant length.
    public static func doublingDifference(
        target: String, response: String
    ) -> (consonant: Character, targetIsDouble: Bool)? {
        guard target != response, collapseDoubleConsonants(target) == collapseDoubleConsonants(response) else {
            return nil
        }
        let t = runs(target)
        let r = runs(response)
        guard t.count == r.count else { return nil }
        for (a, b) in zip(t, r) where a.count != b.count {
            return (a.char, a.count > b.count)
        }
        return nil
    }

    private static func runs(_ text: String) -> [(char: Character, count: Int)] {
        var result: [(char: Character, count: Int)] = []
        for c in text {
            if let last = result.last, last.char == c, consonants.contains(c) {
                result[result.count - 1].count += 1
            } else {
                result.append((c, 1))
            }
        }
        return result
    }
}
