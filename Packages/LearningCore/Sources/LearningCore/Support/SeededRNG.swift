import Foundation

/// FNV-1a 64 over the UTF-8 bytes of a string (docs/05 § Determinism helpers). Never use `hashValue`.
public enum FNV1a64 {
    public static let offsetBasis: UInt64 = 0xcbf2_9ce4_8422_2325
    public static let prime: UInt64 = 0x0000_0100_0000_01b3

    public static func hash(_ string: String) -> UInt64 {
        var h = offsetBasis
        for byte in string.utf8 {
            h ^= UInt64(byte)
            h = h &* prime
        }
        return h
    }
}

/// SplitMix64: the only random source for shuffles and picks. Seed it with `FNV1a64.hash(seedString)`.
public struct SplitMix64: RandomNumberGenerator, Sendable {
    private var state: UInt64

    public init(seed: UInt64) { state = seed }
    public init(seedString: String) { state = FNV1a64.hash(seedString) }

    public mutating func next() -> UInt64 {
        state = state &+ 0x9e37_79b9_7f4a_7c15
        var z = state
        z = (z ^ (z >> 30)) &* 0xbf58_476d_1ce4_e5b9
        z = (z ^ (z >> 27)) &* 0x94d0_49bb_1331_11eb
        return z ^ (z >> 31)
    }

    /// A uniform integer in `0..<upperBound` (Lemire-free modulo with rejection, identical on every platform).
    public mutating func nextInt(below upperBound: Int) -> Int {
        precondition(upperBound > 0)
        let bound = UInt64(upperBound)
        let limit = UInt64.max - (UInt64.max % bound)
        var x = next()
        while x >= limit { x = next() }
        return Int(x % bound)
    }
}

extension Array {
    /// Fisher–Yates with `SplitMix64.nextInt(below:)`, so every device produces the same order.
    /// (Swift's `shuffled(using:)` is not guaranteed stable across standard-library versions.)
    public func seededShuffle(using rng: inout SplitMix64) -> [Element] {
        var a = self
        guard a.count > 1 else { return a }
        for i in stride(from: a.count - 1, to: 0, by: -1) {
            let j = rng.nextInt(below: i + 1)
            if i != j { a.swapAt(i, j) }
        }
        return a
    }

    public func seededShuffle(seed: String) -> [Element] {
        var rng = SplitMix64(seedString: seed)
        return seededShuffle(using: &rng)
    }
}
