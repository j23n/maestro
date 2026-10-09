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
///
/// The doubling word (*doppia*, the pack's `c:doppia`) lets a spelled answer say a double letter either way (CL40:
/// *doppia esse* or *esse esse*); it is never mapped to, only read (`LetterReader`).
public struct LetterNames: Sendable, Hashable {
    /// Lowercase letter (a one-character string) → the normalised tokens of its name.
    let names: [String: [String]]
    /// The doubling word's normalised tokens, when the pack has one.
    public let doubling: [String]?

    /// - Parameters:
    ///   - names: letter (`"B"`: one ASCII letter, either case) → its Italian name as the pack writes it (`"bi"`,
    ///     `"i lunga"`). An entry whose key isn't one ASCII letter, or whose name normalises to nothing, is left out
    ///     (the pack reader refuses such a row before it gets here).
    ///   - doubling: the doubling word as the pack writes it (`c:doppia`'s `it`), if any.
    public init(_ names: [String: String] = [:], doubling: String? = nil) {
        var map: [String: [String]] = [:]
        for (letter, name) in names {
            guard let key = Self.key(letter) else { continue }
            let tokens = Normalizer.tokens(name)
            if !tokens.isEmpty { map[key] = tokens }
        }
        self.names = map
        let doublingTokens = doubling.map(Normalizer.tokens) ?? []
        self.doubling = doublingTokens.isEmpty ? nil : doublingTokens
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
    public func apply(_ tokens: [String]) -> [String] { marking(tokens).tokens }

    /// `apply(_:)`, plus the indices of the output tokens that are surely letters: those mapped from a single
    /// consonant (a vowel may be the word *a*, *e*, *i*, *o*) or from single letters joined by hyphens. Spelled
    /// answers count such a letter next to a spelling as an extra letter (CL40, `LetterReader`).
    public func marking(_ tokens: [String]) -> (tokens: [String], spelled: Set<Int>) {
        guard !names.isEmpty else { return (tokens, []) }
        var out: [String] = []
        var sure = Set<Int>()
        out.reserveCapacity(tokens.count)
        for token in tokens {
            if let spelled = spelled(token) {
                if token.contains("-") || spelled != [token] {
                    sure.formUnion(out.count..<(out.count + spelled.count))
                }
                out.append(contentsOf: spelled)
            } else {
                out.append(token)
            }
        }
        return (out, sure)
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
