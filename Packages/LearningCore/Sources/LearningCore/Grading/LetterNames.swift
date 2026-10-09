import Foundation

/// Spoken spelling (docs/05 § Speech transcripts, step 2; CL25). A recogniser writes a spelled name as single letters
/// (*M A R C O*, *M-A-R-C-O*, *m. a. r. c. o.*), never as the Italian letter names the answer patterns use (*emme, a,
/// erre, ci, o*), so the transcript matcher and spoken content points map each standalone single-letter token of a
/// normalised transcript to its name before matching: *m* → *emme*, *j* → *i lunga*, *w* → *doppia vu*.
///
/// The table comes from the pack's letter items (`items.letter`, docs/03 § Items), never from Swift (hard rule 6).
/// A vowel's name is the vowel itself, so *a*, *e*, *i*, *o* in ordinary sentences stay as they are. A token of single
/// letters joined by hyphens (`m-a-r-c-o`: the normaliser keeps a hyphen between two letters) is spelled too; a token
/// with any longer part (`e-mail`) is not. Patterns and typed answers are never mapped.
public struct LetterNames: Sendable, Hashable {
    /// Lowercase letter (a one-character string) → the normalised tokens of its name.
    private let names: [String: [String]]

    /// - Parameter names: letter (`"B"`: one ASCII letter, either case) → its Italian name as the pack writes it
    ///   (`"bi"`, `"i lunga"`). An entry whose key isn't one ASCII letter, or whose name normalises to nothing, is
    ///   left out (the pack reader refuses such a row before it gets here).
    public init(_ names: [String: String] = [:]) {
        var map: [String: [String]] = [:]
        for (letter, name) in names {
            guard let key = Self.key(letter) else { continue }
            let tokens = Normalizer.tokens(name)
            if !tokens.isEmpty { map[key] = tokens }
        }
        self.names = map
    }

    /// No letters: transcripts are matched as they are (a pack without letter items).
    public static let empty = LetterNames()

    public var isEmpty: Bool { names.isEmpty }

    /// How many letters have a name.
    public var count: Int { names.count }

    /// The lowercase key of a letter (`"M"` → `"m"`), or nil when `letter` isn't one ASCII letter.
    public static func key(_ letter: String) -> String? {
        guard letter.count == 1, let c = letter.first, c.isASCII, c.isLetter else { return nil }
        return letter.lowercased()
    }

    /// The name of `letter` as normalised tokens (`"m"` → `["emme"]`, `"J"` → `["i", "lunga"]`), or nil.
    public func name(of letter: String) -> [String]? {
        Self.key(letter).flatMap { names[$0] }
    }

    /// `tokens` (normalised, as `Normalizer.tokens` gives them) with every spelled letter replaced by its name's
    /// tokens: `["m", "a", "r", "c", "o"]` → `["emme", "a", "erre", "ci", "o"]`, `["doppia", "s"]` →
    /// `["doppia", "esse"]`. Every other token is kept as it is.
    public func apply(_ tokens: [String]) -> [String] {
        guard !names.isEmpty else { return tokens }
        var out: [String] = []
        out.reserveCapacity(tokens.count)
        for token in tokens {
            if let spelled = spelled(token) {
                out.append(contentsOf: spelled)
            } else {
                out.append(token)
            }
        }
        return out
    }

    /// The names of a spelled token: one letter (`m`), or single letters joined by hyphens (`m-a-r-c-o`).
    func spelled(_ token: String) -> [String]? {
        if let name = names[token] { return name }
        guard token.contains("-") else { return nil }
        var out: [String] = []
        for part in token.split(separator: "-", omittingEmptySubsequences: false) {
            guard let name = names[String(part)] else { return nil }
            out.append(contentsOf: name)
        }
        return out
    }
}
