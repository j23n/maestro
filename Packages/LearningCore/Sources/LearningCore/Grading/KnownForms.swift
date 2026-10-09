import Foundation

/// The pack's `forms` table as the graders use it: normalised surface form → the items it is a form of.
/// It tells an inflection error (*americana* for *americano*: same item) from a real but wrong word (*te* for
/// *tè*: another item), and feeds the writing spelling suggestions (docs/05 § Grading).
public struct KnownForms: Sendable, Hashable {
    private let map: [String: Set<ItemID>]
    /// Every character used by a known form, sorted (the alphabet for spelling suggestions).
    private let alphabet: [Character]
    /// Elided form → the full form it stands for (`anch'` → `anche`; see `elisionReadings`).
    public let elisions: [String: String]
    /// Full form → its elided form (`anche` → `anch'`).
    private let elided: [String: String]

    public init(_ map: [String: Set<ItemID>] = [:]) {
        self.map = map
        alphabet = Set(map.keys.joined()).sorted()
        elisions = Self.elisions(map)
        var elided: [String: String] = [:]
        var twice = Set<String>()
        for (short, full) in elisions {
            if elided.updateValue(short, forKey: full) != nil { twice.insert(full) }
        }
        for full in twice { elided.removeValue(forKey: full) }
        self.elided = elided
    }

    /// The pairs the forms table itself gives: a form ending in an apostrophe (`anch'`) stands for the one form of
    /// the same item that is its stem plus one letter (`anche`: `w:anche` has both). A form with several candidates
    /// is left out: `l'` (the article's *lo*, *la*, *le*), `un'` (*un*, *uno*, *una*). So no table of Italian
    /// elisions lives in Swift (hard rule 6); the pack's `forms` table knows the ones the course uses.
    static func elisions(_ map: [String: Set<ItemID>]) -> [String: String] {
        var forms: [ItemID: [String]] = [:]
        for (form, items) in map {
            for item in items { forms[item, default: []].append(form) }
        }
        var out: [String: String] = [:]
        for (form, items) in map
        where form.count >= 2 && form.hasSuffix("'") && form.dropLast().allSatisfy(\.isLetter) {
            let stem = form.dropLast()
            let full = Set(
                items.flatMap { forms[$0] ?? [] }.filter {
                    $0.count == form.count && $0.hasPrefix(stem) && $0.allSatisfy(\.isLetter)
                })
            if full.count == 1, let only = full.first { out[form] = only }
        }
        return out
    }

    /// A transcript's tokens and the readings an elision allows (docs/05 § Speech transcripts, CL31): each elided
    /// word glued to the next (`anch'io`) read in full (`anche io`), and each full form the forms table can elide read
    /// glued to the next word (`anche io` → `anch'io`). The tokens as heard come first; a token the table doesn't
    /// pair (`l'amico`, `c'è`) stays as it is in every reading.
    public func elisionReadings(_ tokens: [String]) -> [[String]] {
        guard !elisions.isEmpty else { return [tokens] }
        var expanded: [String] = []
        for token in tokens {
            if let mark = token.firstIndex(of: "'"), mark != token.index(before: token.endIndex),
                let full = elisions[String(token[...mark])]
            {
                expanded += [full, String(token[token.index(after: mark)...])]
            } else {
                expanded.append(token)
            }
        }
        var contracted: [String] = []
        var i = 0
        while i < tokens.count {
            if i + 1 < tokens.count, let short = elided[tokens[i]] {
                contracted.append(short + tokens[i + 1])
                i += 2
            } else {
                contracted.append(tokens[i])
                i += 1
            }
        }
        var out = [tokens]
        for reading in [expanded, contracted] where !out.contains(reading) { out.append(reading) }
        return out
    }

    /// Builds the map from `(form, itemId)` rows.
    public init<S: Sequence>(rows: S) where S.Element == (form: String, itemID: ItemID) {
        var map: [String: Set<ItemID>] = [:]
        for row in rows { map[row.form, default: []].insert(row.itemID) }
        self.init(map)
    }

    public static let empty = KnownForms()

    public var count: Int { map.count }

    public func contains(_ form: String) -> Bool { map[form] != nil }

    /// The items `form` is a form of (empty when unknown).
    public func items(of form: String) -> Set<ItemID> { map[form] ?? [] }

    /// True when both are known forms of at least one common item (*un* and *una*; *americano* and *americana*).
    public func areFormsOfSameItem(_ a: String, _ b: String) -> Bool {
        guard let x = map[a], let y = map[b] else { return false }
        return !x.isDisjoint(with: y)
    }

    /// Known forms at Damerau-Levenshtein distance 1 from `token` (an accent counts as a letter), sorted.
    /// Empty when `token` is itself a known form.
    public func suggestions(for token: String) -> [String] {
        guard !contains(token), !token.isEmpty else { return [] }
        let chars = Array(token)
        var found = Set<String>()
        func check(_ candidate: [Character]) {
            let s = String(candidate)
            if map[s] != nil { found.insert(s) }
        }
        for i in chars.indices {
            var deleted = chars
            deleted.remove(at: i)
            check(deleted)
            if i + 1 < chars.count {
                var swapped = chars
                swapped.swapAt(i, i + 1)
                check(swapped)
            }
            for a in alphabet where a != chars[i] {
                var replaced = chars
                replaced[i] = a
                check(replaced)
            }
        }
        for i in 0...chars.count {
            for a in alphabet {
                var inserted = chars
                inserted.insert(a, at: i)
                check(inserted)
            }
        }
        found.remove(token)
        return found.sorted()
    }
}
