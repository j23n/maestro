import Foundation

/// Known % and "good fit" (HANDOFF.md 3.5, 5.1). Known % is the share of running words whose lemma
/// the learner knows; 90 to 97% is a good fit for comfortable reading.
public enum KnownWords {
    public static let goodFit: ClosedRange<Double> = 0.90...0.97

    /// lemma -> count of running words in a text.
    public static func fraction(lemmaCounts: [String: Int], known: Set<String>) -> Double {
        let total = lemmaCounts.values.reduce(0, +)
        guard total > 0 else { return 0 }
        let knownCount = lemmaCounts.reduce(0) { $0 + (known.contains($1.key) ? $1.value : 0) }
        return Double(knownCount) / Double(total)
    }

    /// Lemmas that count as known: kept items, plus lemmas seen in at least `minTexts` finished texts,
    /// plus a baseline (for example the core vocabulary below the learner's level).
    public static func knownLemmas(kept: Set<String>, finishedTexts: [[String: Int]], baseline: Set<String> = [],
                                   minTexts: Int = 2) -> Set<String> {
        var seen: [String: Int] = [:]
        for text in finishedTexts {
            for lemma in text.keys { seen[lemma, default: 0] += 1 }
        }
        let fromReading = Set(seen.filter { $0.value >= minTexts }.keys)
        return kept.union(fromReading).union(baseline)
    }
}
