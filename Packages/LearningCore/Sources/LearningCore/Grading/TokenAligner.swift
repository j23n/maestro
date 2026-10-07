import Foundation

/// Token-level weighted edit distance with wildcard slots (docs/05 § Typed answers 2; also dictation).
///
/// Costs are integers in tenths (0.1 → 1, 0.5 → 5, 1 → 10) so ties compare exactly. Among equal costs the
/// alignment with fewer hard operations (substitution, insertion, deletion) wins, then the one with more exact
/// pairs, then pairing over deleting over inserting, so results are deterministic.
///
/// The exact-pair tie-break keeps a wildcard slot from taking a word an expected literal matches exactly: for
/// `mi chiamo` against `mi chiamo {NAME}`, "pair *chiamo*, the slot is missing" and "*chiamo* is missing, the slot
/// takes it" both cost one deletion, and the first has one more exact pair. (A slot can never do better than that
/// tie: whatever run it takes besides the literal's word, the literal could pair that word and the slot keep the
/// rest.)
enum TokenAligner {
    struct Cost: Comparable, Hashable {
        var total: Int
        var hard: Int
        /// Expected tokens paired with an identical response token (cost 0).
        var exact: Int = 0

        static let zero = Cost(total: 0, hard: 0)

        static func < (a: Cost, b: Cost) -> Bool { (a.total, a.hard, -a.exact) < (b.total, b.hard, -b.exact) }
        static func + (a: Cost, b: Cost) -> Cost {
            Cost(total: a.total + b.total, hard: a.hard + b.hard, exact: a.exact + b.exact)
        }
    }

    enum Op<Mark: Hashable>: Hashable {
        /// An expected word token paired with a response token; `mark` says how they compare.
        case pair(expected: Int, response: Int, mark: Mark)
        /// A slot filled by a run of response tokens.
        case slot(expected: Int, response: Range<Int>)
        case delete(expected: Int)
        case insert(response: Int)
    }

    /// How an expected token pairs with a response token.
    struct Pairing<Mark> {
        var mark: Mark
        var cost: Int
        var hard: Bool
    }

    /// Aligns `expectedCount` expected tokens with `responseCount` response tokens.
    /// - Parameters:
    ///   - indel: the cost of an insertion or a deletion.
    ///   - slotRange: for a slot token, how many response tokens it may take; nil for a word token.
    ///   - slotAccepts: whether a slot token may take the given response tokens.
    ///   - pair: how an expected word token pairs with a response token.
    static func align<Mark: Hashable>(
        expectedCount n: Int, responseCount m: Int, indel: Int = 10,
        slotRange: (Int) -> ClosedRange<Int>?,
        slotAccepts: (Int, Range<Int>) -> Bool,
        pair: (Int, Int) -> Pairing<Mark>
    ) -> (cost: Cost, ops: [Op<Mark>]) {
        let width = m + 1
        var best = [Cost?](repeating: nil, count: (n + 1) * width)
        var back = [(from: Int, op: Op<Mark>)?](repeating: nil, count: (n + 1) * width)
        best[0] = .zero

        func relax(_ to: Int, _ cost: Cost, from: Int, _ op: Op<Mark>) {
            if let current = best[to], !(cost < current) { return }
            best[to] = cost
            back[to] = (from, op)
        }

        let indelStep = Cost(total: indel, hard: 1)
        for i in 0...n {
            for j in 0...m {
                let here = i * width + j
                guard let cost = best[here] else { continue }
                if i < n {
                    if let range = slotRange(i) {
                        for k in range where k > 0 && j + k <= m && slotAccepts(i, j..<(j + k)) {
                            relax((i + 1) * width + j + k, cost, from: here, .slot(expected: i, response: j..<(j + k)))
                        }
                    } else if j < m {
                        let p = pair(i, j)
                        let step = Cost(total: p.cost, hard: p.hard ? 1 : 0, exact: p.cost == 0 && !p.hard ? 1 : 0)
                        let op = Op.pair(expected: i, response: j, mark: p.mark)
                        relax((i + 1) * width + j + 1, cost + step, from: here, op)
                    }
                    relax((i + 1) * width + j, cost + indelStep, from: here, .delete(expected: i))
                }
                if j < m { relax(here + 1, cost + indelStep, from: here, .insert(response: j)) }
            }
        }

        var ops: [Op<Mark>] = []
        var cell = n * width + m
        while cell != 0, let link = back[cell] {
            ops.append(link.op)
            cell = link.from
        }
        return (best[n * width + m] ?? .zero, ops.reversed())
    }
}
