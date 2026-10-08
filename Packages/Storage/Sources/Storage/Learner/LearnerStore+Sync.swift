import Foundation
import GRDB
import LearningCore

/// A record waiting for upload (`sync_pending`, docs/08 § The sync engine).
public struct PendingChange: Sendable, Hashable {
    /// The event UUID, or `setting.<key>`.
    public var recordName: String
    public var recordType: SyncRecordType
    public var addedAt: Int64

    public init(recordName: String, recordType: SyncRecordType, addedAt: Int64) {
        self.recordName = recordName
        self.recordType = recordType
        self.addedAt = addedAt
    }
}

/// The sync bookkeeping `CloudSync` (task M7.2) reads and writes: pending changes, the engine's state
/// serialization, cached system fields, the records to upload, and the erase that zone deletion and Reset need.
/// Everything here is CloudKit-agnostic: records are LearningCore's `SyncRecord`, system fields opaque bytes.
extension LearnerStore {
    /// Every pending change, oldest first.
    public func pendingChanges() async throws(StorageError) -> [PendingChange] {
        try await read { db in
            try Row.fetchAll(
                db, sql: "SELECT record_name, kind, added_at FROM sync_pending ORDER BY added_at, record_name"
            )
            .map { row in
                let name = try row.decode(String.self, atIndex: 0)
                let kind = try row.decode(String.self, atIndex: 1)
                return PendingChange(
                    recordName: name,
                    recordType: SyncRecordType(rawValue: kind)
                        ?? RecordMapping.recordType(forRecordName: name),
                    addedAt: try row.decode(Int64.self, atIndex: 2))
            }
        }
    }

    /// Marks records pending (again): after a `.zoneNotFound` or `.unknownItem` save error, or a setting conflict
    /// the local value won. Names already pending keep their original time.
    public func addPending(recordNames: [String]) async throws(StorageError) {
        let now = clock.nowMs()
        try await write { db in
            try db.inTransaction {
                for name in recordNames {
                    try SyncTables.addPending(
                        db, recordName: name, type: RecordMapping.recordType(forRecordName: name),
                        at: now)
                }
                return .commit
            }
        }
    }

    /// Removes records the server accepted (`.sentRecordZoneChanges`).
    public func removePending(recordNames: [String]) async throws(StorageError) {
        try await write { db in
            try db.inTransaction {
                let delete = try db.cachedStatement(sql: "DELETE FROM sync_pending WHERE record_name = ?")
                for name in recordNames { try delete.execute(arguments: [name]) }
                return .commit
            }
        }
    }

    /// Marks every event and every synced setting pending: the first upload after signing in to iCloud, and
    /// `.encryptedDataReset` (docs/08). The server treats events it already has as success. Returns how many
    /// records are pending afterwards.
    @discardableResult
    public func markEverythingPending() async throws(StorageError) -> Int {
        let now = clock.nowMs()
        return try await write { db in
            try db.inTransaction {
                try db.execute(
                    sql: """
                        INSERT INTO sync_pending (record_name, kind, added_at) SELECT id, ?, ? FROM events WHERE true
                        ON CONFLICT(record_name) DO NOTHING
                        """, arguments: [SyncRecordType.event.rawValue, now])
                try db.execute(
                    sql: """
                        INSERT INTO sync_pending (record_name, kind, added_at)
                        SELECT ? || key, ?, ? FROM settings WHERE scope = 'synced' ON CONFLICT(record_name) DO NOTHING
                        """, arguments: [RecordMapping.settingRecordPrefix, SyncRecordType.setting.rawValue, now])
                return .commit
            }
            return try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM sync_pending") ?? 0
        }
    }

    /// The record to upload for a pending record name, or nil when its row is gone (then `CloudSync` drops the
    /// pending change) or the setting is device-scoped. An event's payload is sent as stored.
    public func syncRecord(named recordName: String) async throws(StorageError) -> SyncRecord? {
        try await read { db in
            switch RecordMapping.recordType(forRecordName: recordName) {
            case .event:
                guard
                    let row = try Row.fetchOne(
                        db, sql: "SELECT \(EventRow.columns) FROM events WHERE id = ?",
                        arguments: [recordName.lowercased()])
                else { return nil }
                let stored = try EventRow(row: row)
                var record: SyncRecord
                do {
                    record = try RecordMapping.record(for: stored.event)
                } catch {
                    throw StorageError.invalidValue(table: "events", id: stored.id, reason: "\(error)")
                }
                record.fields[RecordMapping.EventField.payload] = .bytes(Data(stored.payload.utf8))
                return record
            case .setting:
                guard let key = RecordMapping.settingKey(fromRecordName: recordName),
                    let setting = try SettingsTable.record(db, key: key), setting.scope == .synced
                else { return nil }
                do {
                    return try RecordMapping.record(for: setting)
                } catch {
                    throw StorageError.invalidValue(table: "settings", id: key, reason: "\(error)")
                }
            }
        }
    }

    /// The saved `CKSyncEngine.State.Serialization` (`sync_engine_state`), or nil on the first run.
    public func syncEngineState() async throws(StorageError) -> Data? {
        try await read { db in try Data.fetchOne(db, sql: "SELECT data FROM sync_engine_state WHERE id = 1") }
    }

    /// Persists the engine's state serialization (`.stateUpdate`), in its own small transaction.
    public func saveSyncEngineState(_ data: Data?) async throws(StorageError) {
        try await write { db in
            try db.execute(sql: "INSERT OR REPLACE INTO sync_engine_state (id, data) VALUES (1, ?)", arguments: [data])
        }
    }

    /// The cached system fields of a record (`cloud_system_fields`).
    public func systemFields(recordName: String) async throws(StorageError) -> Data? {
        try await read { db in
            try Data.fetchOne(
                db, sql: "SELECT data FROM cloud_system_fields WHERE record_name = ?",
                arguments: [recordName])
        }
    }

    public func saveSystemFields(_ data: Data, recordName: String) async throws(StorageError) {
        try await write { db in
            try db.execute(
                sql: "INSERT OR REPLACE INTO cloud_system_fields (record_name, data) VALUES (?, ?)",
                arguments: [recordName, data])
        }
    }

    /// Forgets cached system fields (`.unknownItem`).
    public func removeSystemFields(recordNames: [String]) async throws(StorageError) {
        try await write { db in
            try db.inTransaction {
                let delete = try db.cachedStatement(sql: "DELETE FROM cloud_system_fields WHERE record_name = ?")
                for name in recordNames { try delete.execute(arguments: [name]) }
                return .commit
            }
        }
    }

    /// Deletes the learner's progress on this device, in one transaction: every event, the derived state, synced
    /// settings, `sync_pending`, `cloud_system_fields` and `telemetry_sent`. Keeps device-scoped settings, the
    /// device ID and the engine's state. The only deletion of events there is (docs/03): for the zone deleted on
    /// another device or purged in iCloud settings, and for Reset progress (docs/08). The derived state becomes
    /// the initial one.
    public func eraseProgress() async throws(StorageError) {
        try await write { db in
            var state = LearnerState()
            var settings = LearnerSettings()
            try db.inTransaction(.immediate) {
                for table in [
                    "events", "sync_pending", "cloud_system_fields", "telemetry_sent", "derived_checkpoint",
                    "derived_meta",
                ] + LearnerSchema.derivedTables {
                    try db.execute(sql: "DELETE FROM \(table)")
                }
                try db.execute(sql: "DELETE FROM settings WHERE scope = 'synced'")
                state = try DerivedStore.rebuild(db, content: self.content, logger: self.logger)
                settings = LearnerSettings(records: try SettingsTable.all(db, logger: self.logger))
                return .commit
            }
            self.publish(state: state, sinceCheckpoint: 0)
            self.publish(settings: settings)
        }
    }
}

/// The `sync_pending` table.
enum SyncTables {
    /// Marks a record pending; a name already pending keeps its original time.
    static func addPending(_ db: Database, recordName: String, type: SyncRecordType, at: Int64) throws {
        try db.cachedStatement(
            sql: """
                INSERT INTO sync_pending (record_name, kind, added_at) VALUES (?, ?, ?)
                ON CONFLICT(record_name) DO NOTHING
                """
        ).execute(arguments: [recordName, type.rawValue, at])
    }
}
