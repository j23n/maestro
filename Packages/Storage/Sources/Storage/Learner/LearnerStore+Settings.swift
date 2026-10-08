import Foundation
import GRDB
import LearningCore

/// Settings (docs/08 § Settings): one `settings` row per key, last-writer-wins by `(updatedAt, deviceId)`.
/// Device-scoped keys never sync; a change to a synced key gets a `sync_pending` row in the same transaction.
extension LearnerStore {
    /// Every stored setting, with the defaults behind it, as of the last commit.
    public var settings: LearnerSettings { live.current.settings }

    /// The current settings, then the settings after every change (local or synced).
    public func settingsUpdates() -> AsyncStream<LearnerSettings> {
        let (stream, continuation) = AsyncStream.makeStream(
            of: LearnerSettings.self,
            bufferingPolicy: .bufferingNewest(1))
        let id = live.withLock { live -> Int in
            let id = live.nextObserver
            live.nextObserver += 1
            live.settingsObservers[id] = continuation
            continuation.yield(live.settings)
            return id
        }
        continuation.onTermination = { [weak self] _ in
            self?.live.withLock { live in live.settingsObservers[id] = nil }
        }
        return stream
    }

    /// Stores a change made on this device. Its `updatedAt` is now, or one millisecond after the stored value's if
    /// that is later (another device's clock ran ahead), so a change the learner just made always wins. A synced
    /// key is also marked pending for upload, in the same transaction, and yielded to `pendingAdditions()` after
    /// the commit (every time, even when it was already pending: its upload may be in flight with the old value).
    @discardableResult
    public func set(_ key: SettingKey, to value: JSONValue) async throws(StorageError) -> SettingRecord {
        let deviceId = deviceId
        let clock = clock
        return try await write { db in
            var stored: SettingRecord?
            try db.inTransaction(.immediate) {
                let current = try SettingsTable.record(db, key: key.rawValue)
                let now = clock.nowMs()
                let updatedAt = current.map { max(now, $0.updatedAt + 1) } ?? now
                let record = SettingRecord(key, value: value, updatedAt: updatedAt, deviceId: deviceId)
                try SettingsTable.upsert(db, record)
                if key.scope == .synced {
                    try SyncTables.addPending(
                        db, recordName: RecordMapping.recordName(forSettingKey: key.rawValue),
                        type: .setting, at: now)
                }
                stored = record
                return .commit
            }
            guard let stored else {
                throw StorageError.invalidValue(table: "settings", id: key.rawValue, reason: "not written")
            }
            self.publish(setting: stored)
            if key.scope == .synced { self.publish(pending: [RecordMapping.recordName(forSettingKey: key.rawValue)]) }
            return stored
        }
    }

    /// Merges a setting received from another device (docs/08 § Merge rules): the remote value is stored when it
    /// wins over the local one; device-scoped keys are never taken. Returns what the merge decided: after a
    /// `serverRecordChanged` conflict, `CloudSync` uploads the local value again on `.keepLocal`.
    @discardableResult
    public func applyRemote(_ remote: SettingRecord) async throws(StorageError) -> MergeRules.SettingResolution {
        try await write { db in
            var resolution = MergeRules.SettingResolution.keepLocal
            var changed: SettingRecord?
            try db.inTransaction(.immediate) {
                let local = try SettingsTable.record(db, key: remote.key)
                resolution = MergeRules.resolve(local: local, remote: remote)
                if resolution == .takeRemote, local != remote {
                    var record = remote
                    record.scope = SettingKey.scope(of: remote.key)
                    try SettingsTable.upsert(db, record)
                    changed = record
                }
                return .commit
            }
            if let changed { self.publish(setting: changed) }
            return resolution
        }
    }

    /// The stored record of a key (nil when it was never set on any device).
    public func settingRecord(_ key: String) async throws(StorageError) -> SettingRecord? {
        try await read { db in try SettingsTable.record(db, key: key) }
    }

    func publish(setting record: SettingRecord) {
        live.withLock { live in
            live.settings.set(record)
            for continuation in live.settingsObservers.values { continuation.yield(live.settings) }
        }
    }

    func publish(settings: LearnerSettings) {
        live.withLock { live in
            live.settings = settings
            for continuation in live.settingsObservers.values { continuation.yield(settings) }
        }
    }
}

/// The `settings` table.
enum SettingsTable {
    static let columns = "key, value, updated_at, device_id, scope"

    static func all(_ db: Database, logger: any CoreLogger) throws -> [SettingRecord] {
        try Row.fetchAll(db, sql: "SELECT \(columns) FROM settings ORDER BY key").compactMap { row in
            do {
                return try record(row)
            } catch {
                logger.log("settings: skipped an unreadable row: \(error)")
                return nil
            }
        }
    }

    static func record(_ db: Database, key: String) throws -> SettingRecord? {
        try Row.fetchOne(db, sql: "SELECT \(columns) FROM settings WHERE key = ?", arguments: [key]).map(record)
    }

    static func record(_ row: Row) throws -> SettingRecord {
        let key = try row.decode(String.self, atIndex: 0)
        let json = try row.decode(String.self, atIndex: 1)
        let value: JSONValue
        do {
            value = try JSONDecoder().decode(JSONValue.self, from: Data(json.utf8))
        } catch {
            throw StorageError.invalidValue(table: "settings", id: key, reason: "value isn't JSON: \(error)")
        }
        let scopeRaw = try row.decode(String.self, atIndex: 4)
        return SettingRecord(
            key: key, value: value, updatedAt: try row.decode(Int64.self, atIndex: 2),
            deviceId: try row.decode(String.self, atIndex: 3),
            scope: SettingScope(rawValue: scopeRaw) ?? SettingKey.scope(of: key))
    }

    static func upsert(_ db: Database, _ record: SettingRecord) throws {
        let json: Data
        do {
            json = try record.valueJSON()
        } catch {
            throw StorageError.invalidValue(table: "settings", id: record.key, reason: "value doesn't encode: \(error)")
        }
        try db.execute(
            sql: "INSERT OR REPLACE INTO settings (\(columns)) VALUES (?, ?, ?, ?, ?)",
            arguments: [
                record.key, String(decoding: json, as: UTF8.self), record.updatedAt, record.deviceId,
                record.scope.rawValue,
            ])
    }
}
