import Foundation

/// Orders a review session's cards (docs/05 § Review session builder, step 3) with the session RNG: never the same
/// item twice in a row, at most 2 consecutive cards of one format, and grammar cards spread evenly.
///
/// The cards are shuffled first; then each position takes the first remaining card (in shuffled order) that keeps
/// the constraints satisfiable for the rest. A grammar card is preferred once the position reaches the next grammar
/// card's ideal slot (`(2k + 1) · n / 2g`), any other card before that. When 2 in a row can't be met (15 recall
/// cards among 18, say), the run limit becomes the smallest one achievable, `⌈c / (n − c + 1)⌉` for the commonest
/// format, so the other cards still break the runs evenly instead of bunching up at the start.
public enum Interleaver {
    public static let maxFormatRun = 2

    public static func interleave(_ cards: [ReviewCard], rng: inout SplitMix64) -> [ReviewCard] {
        guard cards.count > 1 else { return cards }
        let shuffled = cards.seededShuffle(using: &rng)
        // Candidates in an order that already spreads each format evenly (grammar and other cards separately).
        var remaining = spreadByFormat(shuffled.filter { !$0.isGrammar }) + spreadByFormat(shuffled.filter(\.isGrammar))
        var counts: [ExerciseFormat: Int] = [:]
        var itemCounts: [ItemID: Int] = [:]
        for card in remaining {
            counts[card.format, default: 0] += 1
            itemCounts[card.pair.itemId, default: 0] += 1
        }
        let n = cards.count
        let limit = runLimit(counts, total: n)
        let grammarTotal = cards.filter(\.isGrammar).count
        var grammarPlaced = 0
        var out: [ReviewCard] = []
        out.reserveCapacity(n)
        var lastFormat: ExerciseFormat?
        var run = 0

        while !remaining.isEmpty {
            let position = out.count
            let wantGrammar =
                grammarPlaced < grammarTotal && position >= idealSlot(grammarPlaced, n: n, of: grammarTotal)
            let order =
                remaining.indices.filter { remaining[$0].isGrammar == wantGrammar }
                + remaining.indices.filter { remaining[$0].isGrammar != wantGrammar }
            let otherItemLeft = { (i: Int) in
                remaining.contains { $0.pair.itemId != remaining[i].pair.itemId }
            }
            func itemOK(_ i: Int) -> Bool {
                guard let previous = out.last else { return true }
                return previous.pair.itemId != remaining[i].pair.itemId || !otherItemLeft(i)
            }
            func runOK(_ i: Int) -> Bool {
                let format = remaining[i].format
                return (format == lastFormat ? run + 1 : 1) <= limit
            }
            func feasibleAfter(_ i: Int) -> Bool {
                let format = remaining[i].format
                var after = counts
                after[format, default: 0] -= 1
                var items = itemCounts
                items[remaining[i].pair.itemId, default: 0] -= 1
                return feasible(after, total: remaining.count - 1, last: format,
                                run: format == lastFormat ? run + 1 : 1, limit: limit)
                    && feasibleItems(items, total: remaining.count - 1, last: remaining[i].pair.itemId)
            }
            let pick =
                order.first { itemOK($0) && runOK($0) && feasibleAfter($0) }
                ?? order.first { itemOK($0) && runOK($0) }
                ?? order.first { itemOK($0) }
                ?? order[0]

            let card = remaining.remove(at: pick)
            counts[card.format, default: 0] -= 1
            itemCounts[card.pair.itemId, default: 0] -= 1
            run = card.format == lastFormat ? run + 1 : 1
            lastFormat = card.format
            if card.isGrammar { grammarPlaced += 1 }
            out.append(card)
        }
        return out
    }

    /// Orders cards so each format is spread evenly: the j-th of a format's m cards sits at `(j + ½) / m`; ties keep
    /// the (shuffled) input order.
    static func spreadByFormat(_ cards: [ReviewCard]) -> [ReviewCard] {
        var counts: [ExerciseFormat: Int] = [:]
        for card in cards { counts[card.format, default: 0] += 1 }
        var seen: [ExerciseFormat: Int] = [:]
        let keyed = cards.enumerated().map { index, card -> (Double, Int, ReviewCard) in
            let j = seen[card.format, default: 0]
            seen[card.format] = j + 1
            return ((Double(j) + 0.5) / Double(counts[card.format] ?? 1), index, card)
        }
        return keyed.sorted { ($0.0, $0.1) < ($1.0, $1.1) }.map(\.2)
    }

    /// 2, or the smallest achievable maximum run when 2 is impossible: `⌈c / (n − c + 1)⌉` for the commonest format.
    public static func runLimit(_ counts: [ExerciseFormat: Int], total: Int) -> Int {
        let commonest = counts.values.max() ?? 0
        let gaps = total - commonest + 1
        return max(maxFormatRun, (commonest + gaps - 1) / gaps)
    }

    /// The ideal position of the k-th of g grammar cards among n.
    static func idealSlot(_ k: Int, n: Int, of g: Int) -> Int {
        g > 0 ? (2 * k + 1) * n / (2 * g) : Int.max
    }

    /// Whether the remaining cards can still be arranged with no item twice in a row, given the last item placed.
    static func feasibleItems(_ counts: [ItemID: Int], total: Int, last: ItemID) -> Bool {
        counts.allSatisfy { item, count in count <= (item == last ? total - count : total - count + 1) }
    }

    /// Whether the remaining formats can still be arranged with runs of at most `limit`, given the run of `last`
    /// that the sequence currently ends with.
    static func feasible(_ counts: [ExerciseFormat: Int], total: Int, last: ExerciseFormat?, run: Int,
                         limit: Int = maxFormatRun) -> Bool
    {
        counts.allSatisfy { format, count in
            let others = total - count
            return count <= (format == last ? limit * others + (limit - run) : limit * (others + 1))
        }
    }
}
