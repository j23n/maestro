import Foundation

/// Splits enclitic pronouns off verb forms: dammelo = da' + me + lo, farlo = fare + lo,
/// parlandogli = parlando + gli (HANDOFF.md 3.2, step 4).
public enum CliticSplitter {
    /// Attached clusters, longest first, with how they read separately.
    static let clusters: [(String, [String])] = {
        var list: [(String, [String])] = []
        for (combined, first) in [("glie", "glie"), ("me", "me"), ("te", "te"), ("ce", "ce"), ("ve", "ve"), ("se", "se")] {
            for second in ["lo", "la", "li", "le", "ne"] {
                list.append((combined + second, [first, second]))
            }
        }
        for single in ["lo", "la", "li", "le", "ne", "mi", "ti", "si", "ci", "vi", "gli"] {
            list.append((single, [single]))
        }
        return list.sorted { $0.0.count > $1.0.count }
    }()

    /// Monosyllabic imperatives that double the clitic's consonant: dammi, fallo, dimmi, stacci, vattene.
    static let shortImperatives = ["da'", "fa'", "di'", "sta'", "va'"]

    public struct Candidate: Sendable, Hashable {
        public let base: String
        public let clitics: [String]
    }

    public static func candidates(for word: String) -> [Candidate] {
        var out: [Candidate] = []
        let w = word.lowercased()
        for (suffix, parts) in clusters where w.hasSuffix(suffix) && w.count > suffix.count + 1 {
            let stem = String(w.dropLast(suffix.count))
            // doubled consonant after a short imperative: dam|melo -> da'
            if let firstLetter = suffix.first, stem.count >= 2, stem.last == firstLetter {
                let short = String(stem.dropLast())
                if let imperative = shortImperatives.first(where: { $0.hasPrefix(short) && $0.count == short.count + 1 }) {
                    out.append(Candidate(base: imperative, clitics: parts))
                }
            }
            out.append(Candidate(base: stem, clitics: parts))            // parlando|gli, guarda|lo
            if stem.hasSuffix("r") {
                out.append(Candidate(base: stem + "e", clitics: parts))   // far|lo -> fare
                out.append(Candidate(base: stem + "re", clitics: parts))  // por|lo -> porre
            }
            // two separate clitics: dandomelo is covered by clusters; vattene = va' + te + ne
            if parts.count == 1 {
                for inner in candidates(for: stem) where inner.clitics.count == 1 {
                    out.append(Candidate(base: inner.base, clitics: inner.clitics + parts))
                }
            }
        }
        var seen = Set<Candidate>()
        return out.filter { seen.insert($0).inserted }
    }
}
