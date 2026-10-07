import Foundation

/// Answer normalisation (docs/05 § Normalisation; `fixtures/grading/normalizer.json` is the reference and the
/// Python pipeline implements the same rules).
///
/// 1. Unicode NFC.  2. ’ ‘ ʼ ´ ` → `'`.  3. Lowercase.  4. Punctuation → space, except `.` `,` `:` between two
/// digits; a hyphen survives only between two letters.  5. No spaces next to apostrophes.  6. Collapse whitespace.
///
/// Lowercasing uses the standard library's `String.lowercased()`, which applies the Unicode default case mapping
/// and never consults a `Locale`, so it gives the same result on every platform. For Italian text it is equivalent
/// to lowercasing with `it_IT`: Italian has no language-specific case rules (only Turkish, Azeri and Lithuanian do).
public enum Normalizer {
    /// docs/05 § Normalisation: these never get accent tolerance (e/è, si/sì …).
    public static let accentSensitiveWords: Set<String> = [
        "e", "è", "si", "sì", "la", "là", "li", "lì", "da", "dà", "se", "sé", "ne", "né", "te", "tè", "di", "dì",
    ]

    /// Step 2: characters typed or pasted for an apostrophe.
    static let apostropheVariants: Set<Character> = ["\u{2019}", "\u{2018}", "\u{02BC}", "\u{00B4}", "`"]

    /// Step 4: punctuation replaced by a space.
    static let punctuation: Set<Character> = [
        ".", ",", ";", ":", "!", "?", "¡", "¿", "«", "»", "\"", "\u{201C}", "\u{201D}", "\u{201E}", "(", ")", "[",
        "]", "\u{2013}", "\u{2014}", "\u{2026}",
    ]

    /// Step 4: kept when both neighbours are digits (`6,20`, `10:15`, `6.20`).
    static let digitSeparators: Set<Character> = [".", ",", ":"]

    /// The normalised form of `text`: lowercase NFC tokens joined by single spaces.
    public static func normalize(_ text: String) -> String {
        tokens(text).joined(separator: " ")
    }

    /// The tokens of the normalised text (the space-separated parts).
    public static func tokens(_ text: String) -> [String] {
        taggedTokens([(text, false)]).map(\.text)
    }

    /// True if `token` is one of the accent-sensitive words (docs/05).
    public static func isAccentSensitive(_ token: String) -> Bool {
        accentSensitiveWords.contains(token)
    }

    /// Removes combining marks after NFD (docs/05): `perché` → `perche`. The result is NFC.
    public static func stripAccents(_ text: String) -> String {
        var scalars = String.UnicodeScalarView()
        for scalar in text.decomposedStringWithCanonicalMapping.unicodeScalars {
            switch scalar.properties.generalCategory {
            case .nonspacingMark, .spacingMark, .enclosingMark: continue
            default: scalars.append(scalar)
            }
        }
        return String(scalars).precomposedStringWithCanonicalMapping
    }

    /// Lowercase, locale-independent (see the type comment).
    public static func lowercase(_ text: String) -> String { text.lowercased() }

    // MARK: - Tagged normalisation (answer patterns carry a focus flag per character)

    struct TaggedToken: Equatable {
        var text: String
        var tagged: Bool
    }

    /// Normalises the concatenation of `pieces`, keeping track of which tokens contain characters from a piece
    /// whose flag is set (the focus spans of an answer pattern).
    static func taggedTokens(_ pieces: [(String, Bool)]) -> [TaggedToken] {
        // Steps 1–3: NFC, apostrophes, lowercase.
        var chars: [(c: Character, tag: Bool)] = []
        for (piece, tag) in pieces {
            for c in piece.precomposedStringWithCanonicalMapping {
                let mapped: Character = apostropheVariants.contains(c) ? "'" : c
                for lower in String(mapped).lowercased() { chars.append((lower, tag)) }
            }
        }
        // Step 4: punctuation and hyphens become spaces (neighbours are judged on the text before replacement).
        var cleaned = chars
        for i in chars.indices {
            let c = chars[i].c
            let prev: Character? = i > 0 ? chars[i - 1].c : nil
            let next: Character? = i + 1 < chars.count ? chars[i + 1].c : nil
            if punctuation.contains(c) {
                if digitSeparators.contains(c), isDigit(prev), isDigit(next) { continue }
                cleaned[i].c = " "
            } else if c == "-" {
                if let prev, let next, prev.isLetter, next.isLetter { continue }
                cleaned[i].c = " "
            }
        }
        // Step 6 first (split on whitespace), then step 5 (glue parts that meet at an apostrophe).
        var parts: [TaggedToken] = []
        var current = TaggedToken(text: "", tagged: false)
        for (c, tag) in cleaned {
            if c.isWhitespace {
                if !current.text.isEmpty { parts.append(current) }
                current = TaggedToken(text: "", tagged: false)
            } else {
                current.text.append(c)
                current.tagged = current.tagged || tag
            }
        }
        if !current.text.isEmpty { parts.append(current) }
        var tokens: [TaggedToken] = []
        for part in parts {
            if let last = tokens.last, last.text.hasSuffix("'") || part.text.hasPrefix("'") {
                tokens[tokens.count - 1] = TaggedToken(text: last.text + part.text, tagged: last.tagged || part.tagged)
            } else {
                tokens.append(part)
            }
        }
        return tokens
    }

    static func isDigit(_ c: Character?) -> Bool {
        guard let c, c.isASCII else { return false }
        return c.isNumber
    }
}
