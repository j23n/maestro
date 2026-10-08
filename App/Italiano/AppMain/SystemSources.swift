import Foundation
import LearningCore

/// The device clock, the only place the App reads wall time for the engine (LearningCore never does, CLAUDE.md
/// rule 3). The UTC offset is read at each call, so travelling across time zones is picked up.
struct SystemClock: LearningCore.Clock {
    func nowMs() -> Int64 { Int64((Date().timeIntervalSince1970 * 1000).rounded(.down)) }
    func tzOffsetMinutes() -> Int { TimeZone.current.secondsFromGMT() / 60 }
}

/// Random version-4 UUIDs, lowercased (docs/05 § Events: event IDs are lowercase).
struct SystemUUIDSource: UUIDSource {
    func next() -> String { UUID().uuidString.lowercased() }
}
