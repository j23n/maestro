import Foundation

/// Normalisation shared by lookup and the reader. Mirrors tools/maestro_content/normalize.py.
public enum Normalizer {
    private static let apostrophes: Set<Character> = ["\u{2019}", "\u{2018}", "\u{02BC}", "`", "\u{00B4}"]

    /// Straight apostrophes.
    public static func apostrophes(_ text: String) -> String {
        String(text.map { apostrophes.contains($0) ? "'" : $0 })
    }

    /// Lowercase, trimmed, straight apostrophes, single spaces.
    public static func query(_ text: String) -> String {
        let cleaned = apostrophes(text).lowercased()
        return cleaned.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }

    /// Lowercase without diacritics: the key for accent-insensitive lookup ("perche" finds "perché").
    public static func fold(_ text: String) -> String {
        var out = String.UnicodeScalarView()
        for scalar in query(text).decomposedScalars where scalar.properties.generalCategory != .nonspacingMark {
            out.append(scalar)
        }
        return String(out)
    }

    /// Splits an elided prefix: "dall'italia" -> ["dall'", "italia"], "l'anno" -> ["l'", "anno"].
    public static func splitElision(_ word: String) -> [String] {
        let w = apostrophes(word)
        guard let idx = w.firstIndex(of: "'"), w.index(after: idx) < w.endIndex else { return [w] }
        let head = String(w[...idx])
        let tail = String(w[w.index(after: idx)...])
        return [head] + splitElision(tail)
    }
}

extension String {
    /// Canonical decomposition, so accents become separate combining scalars.
    fileprivate var decomposedScalars: String.UnicodeScalarView {
        decomposedStringWithCanonicalMapping.unicodeScalars
    }
}
