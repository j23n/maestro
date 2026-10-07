import Foundation
import LearningCore

/// Search for the Words screen (docs/07): built once from every item and its forms, then queried synchronously on
/// each keystroke. Matching ignores case, punctuation and accents (`caffe` finds *caffè*), matches Italian (the
/// lemma, the display forms and every surface form, so `cornetti` finds *cornetto*) and English (the gloss and
/// the alternative glosses), and ranks:
///
/// 1. an Italian key equal to the query, 2. an Italian word starting with it, 3. an English key equal to it,
/// 4. an English word starting with it, 5. an Italian substring, 6. an English substring;
///
/// then by unit order and item ID. The screen filters (unit, kind, the learner's introduced items) with `include`.
public struct PackSearchIndex: Sendable {
    struct Entry: Sendable {
        let item: PackItem
        let unitOrd: Int
        let italian: [String]
        let english: [String]
    }

    let entries: [Entry]

    init(items: [PackItem], forms: [ItemID: [String]], unitOrder: [UnitID: Int]) {
        entries = items.map { item in
            let italian = [item.it, item.displayDef, item.displayIndef].compactMap { $0 } + (forms[item.id] ?? [])
            let english = [item.glossEn] + item.altGlossesEn
            return Entry(
                item: item, unitOrd: unitOrder[item.unitId] ?? Int.max,
                italian: Self.unique(italian.map(Self.fold)), english: Self.unique(english.map(Self.fold)))
        }
    }

    public var count: Int { entries.count }

    /// The query folded the way keys are: normalised (docs/05 § Normalisation) and accent-free.
    static func fold(_ text: String) -> String { Normalizer.stripAccents(Normalizer.normalize(text)) }

    private static func unique(_ keys: [String]) -> [String] {
        var seen = Set<String>()
        return keys.filter { !$0.isEmpty && seen.insert($0).inserted }
    }

    /// Items matching `query`, best first, at most `limit`. An empty query matches nothing.
    public func search(_ query: String, limit: Int = 50, include: (PackItem) -> Bool = { _ in true }) -> [PackItem] {
        let q = Self.fold(query)
        guard !q.isEmpty, limit > 0 else { return [] }
        var hits: [(rank: Int, entry: Entry)] = []
        for entry in entries {
            guard let rank = Self.rank(of: entry, for: q), include(entry.item) else { continue }
            hits.append((rank, entry))
        }
        hits.sort { a, b in
            (a.rank, a.entry.unitOrd, a.entry.item.id.rawValue) < (b.rank, b.entry.unitOrd, b.entry.item.id.rawValue)
        }
        return hits.prefix(limit).map(\.entry.item)
    }

    /// 0…5 as in the type comment, or nil for no match.
    static func rank(of entry: Entry, for q: String) -> Int? {
        func wordStarts(_ key: String) -> Bool {
            key.hasPrefix(q) || key.split(separator: " ").contains { $0.hasPrefix(q) }
                || key.split(separator: "'").dropFirst().contains { $0.hasPrefix(q) }
        }
        if entry.italian.contains(q) { return 0 }
        if entry.italian.contains(where: wordStarts) { return 1 }
        if entry.english.contains(q) { return 2 }
        if entry.english.contains(where: wordStarts) { return 3 }
        if entry.italian.contains(where: { $0.contains(q) }) { return 4 }
        if entry.english.contains(where: { $0.contains(q) }) { return 5 }
        return nil
    }
}
