import Foundation
import LanguageCore
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

/// What the wrap-up offers to keep in Remember, in the sentence of the first drill that needed help:
/// a Grammar card for a grammar topic, a Word card for a new word, a Verb form card for a verb form.
public struct KeepSuggestion: Sendable, Hashable, Identifiable {
    public enum Item: Sendable, Hashable {
        case grammar(topic: String)
        case word(lemmaID: String, senseID: String, surface: String)
        case verbForm(lemmaID: String, formTag: String, surface: String)
    }

    public let item: Item
    public let drill: Drill
    /// Where the item is in the drill's sentence.
    public let range: UTF16Range?

    public var id: String {
        switch item {
        case .grammar(let topic): "grammar|\(topic)"
        case .word(let lemma, let sense, _): "word|\(lemma)|\(sense)"
        case .verbForm(let lemma, let tag, _): "verbForm|\(lemma)|\(tag)"
        }
    }

    /// The grammar topic, for a Grammar suggestion.
    public var topic: String {
        if case .grammar(let topic) = item { return topic }
        return ""
    }
}

public enum PracticeSummary {
    /// What to offer in Remember, in drill order, one per item: grammar topics with a drill not right on
    /// the first try, and the words and verb forms of Words and Verbs drills that weren't. `text` finds the
    /// token a word or verb drill is about; without it only grammar is offered. Say it has nothing to keep yet.
    public static func keepSuggestions(_ drills: [Drill], outcomes: [String: Outcome],
                                       text: ReadingText? = nil) -> [KeepSuggestion] {
        var seen: Set<String> = []
        var out: [KeepSuggestion] = []
        for drill in drills where (outcomes[drill.id] ?? .firstTry) != .firstTry {
            guard let suggestion = suggestion(for: drill, text: text), seen.insert(suggestion.id).inserted else { continue }
            out.append(suggestion)
        }
        return out
    }

    static func suggestion(for drill: Drill, text: ReadingText?) -> KeepSuggestion? {
        let range = drill.r ?? drill.focus
        switch drill.strandKind {
        case .grammar:
            return KeepSuggestion(item: .grammar(topic: drill.topic), drill: drill, range: drill.r)
        case .words, .verbs:
            guard let text, let range, let sentence = text.sentence(drill.sentence),
                  let token = sentence.tokens.first(where: { $0.r == range }), let lemma = token.lemmaID ?? drill.lemma
            else { return nil }
            if drill.strandKind == .verbs, let tag = token.form {
                return KeepSuggestion(item: .verbForm(lemmaID: lemma, formTag: tag, surface: token.t), drill: drill, range: range)
            }
            guard drill.strandKind == .words, let sense = token.senseID else { return nil }
            return KeepSuggestion(item: .word(lemmaID: lemma, senseID: sense, surface: token.t), drill: drill, range: range)
        case .say:
            return nil
        }
    }

    public static func firstTries(_ drills: [Drill], outcomes: [String: Outcome]) -> Int {
        drills.filter { outcomes[$0.id] == .firstTry }.count
    }
}
