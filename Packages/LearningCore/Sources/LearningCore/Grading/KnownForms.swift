import Foundation

/// The pack's `forms` table as the graders use it: normalised surface form → the items it is a form of.
/// It tells an inflection error (*americana* for *americano*: same item) from a real but wrong word (*te* for
/// *tè*: another item), and feeds the writing spelling suggestions (docs/05 § Grading).
public struct KnownForms: Sendable, Hashable {
    private let map: [String: Set<ItemID>]
    /// Every character used by a known form, sorted (the alphabet for spelling suggestions).
    private let alphabet: [Character]

    public init(_ map: [String: Set<ItemID>] = [:]) {
        self.map = map
        alphabet = Set(map.keys.joined()).sorted()
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
