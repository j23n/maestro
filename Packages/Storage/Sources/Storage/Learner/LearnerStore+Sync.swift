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
    /// The record names each local write marks pending, yielded after its commit: the new events of `append` and
    /// `enqueueAppend`, and `setting.<key>` for every `set` of a synced key. `CloudSync` adds them to the sync
    /// engine (docs/08 § New local events). The writes the sync driver makes itself (`addPending`,
    /// `markEverythingPending`) don't yield: it adds those to the engine itself. Nothing is dropped (unbounded
    /// buffer); whatever a crash loses between the commit and the engine is still in `sync_pending`, which the
    /// driver reconciles at launch. The stream finishes when the store closes.
    public func pendingAdditions() -> AsyncStream<[String]> {
        let (stream, continuation) = AsyncStream.makeStream(of: [String].self, bufferingPolicy: .unbounded)
        let id = live.withLock { live -> Int in
            let id = live.nextObserver
            live.nextObserver += 1
            live.pendingObservers[id] = continuation
            return id
        }
        continuation.onTermination = { [weak self] _ in
            self?.live.withLock { live in live.pendingObservers[id] = nil }
        }
        return stream
    }

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

    /// Forgets cached system fields (`.unknownItem`, `.zoneNotFound`).
    public func removeSystemFields(recordNames: [String]) async throws(StorageError) {
        try await write { db in
            try db.inTransaction {
                let delete = try db.cachedStatement(sql: "DELETE FROM cloud_system_fields WHERE record_name = ?")
                for name in recordNames { try delete.execute(arguments: [name]) }
                return .commit
            }
        }
    }

    /// Forgets every cached system field (`.encryptedDataReset`: the server's records are gone, so their change
    /// tags mean nothing).
    public func removeAllSystemFields() async throws(StorageError) {
        try await write { db in try db.execute(sql: "DELETE FROM cloud_system_fields") }
    }

    /// The iCloud account (the CloudKit user record name) this database syncs with; nil until it first syncs. It
    /// lives in `local_meta` (device-local, never synced, kept by `eraseProgress`), so a sign-in to a different
    /// account is recognised as an account switch even after a sign-out in between (docs/08 § `.accountChange`).
    public func syncAccount() async throws(StorageError) -> String? {
        try await read { db in
            try String.fetchOne(db, sql: "SELECT value FROM local_meta WHERE key = ?", arguments: [Self.accountKey])
        }
    }

    /// Binds the database to an iCloud account (nil unbinds it).
    public func setSyncAccount(_ userRecordName: String?) async throws(StorageError) {
        try await write { db in
            if let userRecordName {
                try db.execute(
                    sql: "INSERT OR REPLACE INTO local_meta (key, value) VALUES (?, ?)",
                    arguments: [Self.accountKey, userRecordName])
            } else {
                try db.execute(sql: "DELETE FROM local_meta WHERE key = ?", arguments: [Self.accountKey])
            }
        }
    }

    static let accountKey = "icloud_account"

    /// The platform of every device that wrote a `session` event, from its latest one: the device list of the
    /// sync status line, "Synced 2 minutes ago · iPhone, iPad, Mac" (docs/08 § Status UI, docs/05 `session`).
    /// Devices without a session event, payloads that aren't JSON and platforms this version doesn't know are
    /// left out.
    public func devicePlatforms() async throws(StorageError) -> [String: Platform] {
        try await read { db in
            // SQLite takes a bare column of a MAX() aggregate from the row that has the maximum.
            let rows = try Row.fetchAll(
                db,
                sql: """
                    SELECT device_id,
                           CASE WHEN json_valid(payload) THEN json_extract(payload, '$.platform') END,
                           MAX(at)
                    FROM events WHERE type = 'session' GROUP BY device_id
                    """)
            var platforms: [String: Platform] = [:]
            for row in rows {
                let device = try row.decode(String.self, atIndex: 0)
                guard let raw = try row.decode(String?.self, atIndex: 1), let platform = Platform(rawValue: raw)
                else { continue }
                platforms[device] = platform
            }
            return platforms
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
