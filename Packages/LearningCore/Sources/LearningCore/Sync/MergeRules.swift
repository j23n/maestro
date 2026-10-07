import Foundation

/// Sync merge rules (docs/08 § Merge rules), CloudKit-agnostic.
///
/// - An event is identified by its ID: insert if absent, ignore if present, never update.
/// - Replay order is `(at, id)` everywhere, so states converge whatever the arrival order. No clock-skew correction.
/// - Settings: last-writer-wins per key by `(updatedAt, deviceId)`; a tie on `updatedAt` goes to the lexically larger
///   `deviceId` (UTF-8 bytes); a full tie (never expected) goes to the larger canonical value JSON, so the merge is
///   commutative and every device keeps the same value. Device-scoped settings never sync.
public enum MergeRules {
    /// The incoming events whose IDs are new (not in `existingIDs`, each ID once), in input order, marked remote.
    public static func newEvents(_ incoming: [Event], existingIDs: Set<String>) -> [Event] {
        var seen = existingIDs
        return incoming.filter { seen.insert($0.id).inserted }.map { event in
            var remote = event
            remote.origin = .remote
            return remote
        }
    }

    /// Inserts remote events into an in-memory log keyed by ID and returns the ones that were new. Events already in
    /// the log are never updated.
    @discardableResult
    public static func insert(_ incoming: [Event], into log: inout [String: Event]) -> [Event] {
        let fresh = newEvents(incoming, existingIDs: Set(log.keys))
        for event in fresh { log[event.id] = event }
        return fresh
    }

    /// Whether `candidate` wins over `current` for the same key.
    public static func wins(_ candidate: SettingRecord, over current: SettingRecord) -> Bool {
        if candidate.updatedAt != current.updatedAt { return candidate.updatedAt > current.updatedAt }
        if candidate.deviceId != current.deviceId {
            return current.deviceId.utf8.lexicographicallyPrecedes(candidate.deviceId.utf8)
        }
        let a = (try? candidate.valueJSON()) ?? Data()
        let b = (try? current.valueJSON()) ?? Data()
        return b.lexicographicallyPrecedes(a)
    }

    public enum SettingResolution: Equatable, Sendable {
        /// Keep the local value (and, after a `serverRecordChanged` conflict, upload it again).
        case keepLocal
        /// Store the remote value.
        case takeRemote
    }

    /// Merges a setting received from another device with the local one.
    public static func resolve(local: SettingRecord?, remote: SettingRecord) -> SettingResolution {
        guard SettingKey.scope(of: remote.key) == .synced else { return .keepLocal }
        guard let local else { return .takeRemote }
        return wins(remote, over: local) ? .takeRemote : .keepLocal
    }

    /// Applies a remote setting to a settings table keyed by key; returns whether the table changed.
    @discardableResult
    public static func apply(_ remote: SettingRecord, to table: inout [String: SettingRecord]) -> Bool {
        guard resolve(local: table[remote.key], remote: remote) == .takeRemote, table[remote.key] != remote else {
            return false
        }
        table[remote.key] = remote
        return true
    }
}
