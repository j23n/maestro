import Foundation
import PackKit

/// Seeded shuffles, so options and tiles appear in the same order on every device and every time:
/// SplitMix64 seeded with FNV-1a 64 over the seed's UTF-8 bytes. Never Swift's `hashValue`, which
/// changes per process.
public enum SeededShuffle {
    public static func fnv1a(_ string: String) -> UInt64 {
        var hash: UInt64 = 0xcbf2_9ce4_8422_2325
        for byte in string.utf8 {
            hash ^= UInt64(byte)
            hash = hash &* 0x0000_0100_0000_01b3
        }
        return hash
    }

    public struct SplitMix64: RandomNumberGenerator {
        var state: UInt64
        public init(seed: UInt64) { state = seed }
        public mutating func next() -> UInt64 {
            state &+= 0x9e37_79b9_7f4a_7c15
            var z = state
            z = (z ^ (z >> 30)) &* 0xbf58_476d_1ce4_e5b9
            z = (z ^ (z >> 27)) &* 0x94d0_49bb_1331_11eb
            return z ^ (z >> 31)
        }
    }

    /// The items in a stable order for this seed (Fisher-Yates). Every order is possible, the given
    /// one included, so an option's place says nothing about whether it's the answer.
    ///
    /// With `avoidingGivenOrder`, an order equal to the given one is rotated by one: for match
    /// pairs, which are given in the answer's order.
    public static func shuffled<T: Equatable>(_ items: [T], seed: String, avoidingGivenOrder: Bool = false) -> [T] {
        guard items.count > 1 else { return items }
        var rng = SplitMix64(seed: fnv1a(seed))
        var out = items
        for i in stride(from: out.count - 1, to: 0, by: -1) {
            let j = Int(rng.next() % UInt64(i + 1))
            out.swapAt(i, j)
        }
        if avoidingGivenOrder && out == items {
            out.append(out.removeFirst())
        }
        return out
    }

    /// A build drill's tiles and distractors, shuffled so the tiles never read in the answer's
    /// order, wherever the distractors land. When they would, the tiles rotate by one among their
    /// own places and the distractors stay put.
    public static func tileBank(tiles: [String], distractors: [String], seed: String) -> [String] {
        let all = tiles + distractors
        var order = shuffled(Array(all.indices), seed: seed)
        let slots = order.indices.filter { order[$0] < tiles.count }
        if tiles.count > 1 && slots.map({ all[order[$0]] }) == tiles {
            let moved = slots.map { order[$0] }
            for (k, slot) in slots.enumerated() { order[slot] = moved[(k + 1) % moved.count] }
        }
        return order.map { all[$0] }
    }
}

/// What the summary offers to keep: one Grammar card per topic the learner needed help with, shown
/// in the sentence of the first drill that needed it.
public struct KeepSuggestion: Sendable, Hashable, Identifiable {
    public let topic: String
    public let drill: Drill
    public var id: String { topic }
}

public enum PracticeSummary {
    /// Topics to offer in Remember, in drill order: those with a drill not right on the first try.
    public static func keepSuggestions(_ drills: [Drill], outcomes: [String: Outcome]) -> [KeepSuggestion] {
        var seen: Set<String> = []
        var out: [KeepSuggestion] = []
        for drill in drills where (outcomes[drill.id] ?? .firstTry) != .firstTry && !seen.contains(drill.topic) {
            seen.insert(drill.topic)
            out.append(KeepSuggestion(topic: drill.topic, drill: drill))
        }
        return out
    }

    public static func firstTries(_ drills: [Drill], outcomes: [String: Outcome]) -> Int {
        drills.filter { outcomes[$0.id] == .firstTry }.count
    }
}
