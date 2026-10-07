import Foundation

/// The only source of new IDs in LearningCore (CLAUDE.md hard rule 3). IDs are lowercase UUID strings.
public protocol UUIDSource: Sendable {
    func next() -> String
}

/// Deterministic IDs for tests and simulations: version-4-shaped UUIDs drawn from SplitMix64.
public final class SeededUUIDSource: UUIDSource, @unchecked Sendable {
    // @unchecked: the generator state is guarded by `lock`.
    private let lock = NSLock()
    private var rng: SplitMix64

    public init(seed: String) { rng = SplitMix64(seedString: seed) }

    public func next() -> String {
        let (a, b) = lock.withLock { (rng.next(), rng.next()) }
        var bytes = [UInt8](repeating: 0, count: 16)
        for i in 0..<8 {
            bytes[i] = UInt8(truncatingIfNeeded: a >> (8 * UInt64(i)))
            bytes[8 + i] = UInt8(truncatingIfNeeded: b >> (8 * UInt64(i)))
        }
        bytes[6] = (bytes[6] & 0x0f) | 0x40
        bytes[8] = (bytes[8] & 0x3f) | 0x80
        let hex = bytes.map { String(format: "%02x", $0) }.joined()
        let parts = [hex.prefix(8), hex.dropFirst(8).prefix(4), hex.dropFirst(12).prefix(4),
                     hex.dropFirst(16).prefix(4), hex.dropFirst(20)]
        return parts.map(String.init).joined(separator: "-")
    }
}

/// A tiny logger so LearningCore can report skipped events without importing `os` (docs/02 § Logging).
public protocol CoreLogger: Sendable {
    func log(_ message: String)
}

public struct NoOpLogger: CoreLogger {
    public init() {}
    public func log(_ message: String) {}
}
