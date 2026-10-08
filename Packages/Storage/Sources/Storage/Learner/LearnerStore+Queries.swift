import Foundation
import GRDB
import LearningCore

/// Reading the event log, and the study telemetry bookkeeping (docs/12 § The endpoint contract).
extension LearnerStore {
    // MARK: Events

    /// The whole log in replay order `(at, id)` (export, debugging, tests).
    public func events() async throws(StorageError) -> [Event] {
        try await read { db in try DerivedStore.events(after: nil, db, logger: self.logger) }
    }

    /// One stored event row, payload as stored.
    public func eventRow(id: String) async throws(StorageError) -> EventRow? {
        try await read { db in
            try Row.fetchOne(
                db, sql: "SELECT \(EventRow.columns) FROM events WHERE id = ?",
                arguments: [id.lowercased()]
            ).map { row in try EventRow(row: row) }
        }
    }

    public func eventCount() async throws(StorageError) -> Int {
        try await read { db in try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM events") ?? 0 }
    }

    /// The `at` of this device's newest event: the `lastAt` an `EventFactory` needs after launch, so this device's
    /// events stay strictly increasing (docs/05 § Events).
    public func lastLocalEventAt() async throws(StorageError) -> Int64? {
        let deviceId = deviceId
        return try await read { db in
            try Int64.fetchOne(db, sql: "SELECT MAX(at) FROM events WHERE device_id = ?", arguments: [deviceId])
        }
    }

    /// An event factory for this device: its device ID, the store's clock, and `lastAt` from the log.
    public func makeEventFactory(packVersion: String, ids: any UUIDSource) async throws(StorageError) -> EventFactory {
        EventFactory(
            deviceId: deviceId, packVersion: packVersion, clock: clock, ids: ids,
            lastAt: try await lastLocalEventAt() ?? Int64.min)
    }

    // MARK: Telemetry (docs/12)

    /// This device's events (`origin = 'local'`) with `at ≥ since` that have no `telemetry_sent` row, oldest first
    /// by `(at, id)`, at most `limit`. Payloads are as stored; the uploader strips what consent doesn't cover.
    public func unsentTelemetryEvents(since: Int64, limit: Int) async throws(StorageError) -> [EventRow] {
        try await read { db in
            try Row.fetchAll(
                db,
                sql: """
                    SELECT \(EventRow.columns) FROM events e
                    WHERE e.origin = 'local' AND e.at >= ?
                      AND NOT EXISTS (SELECT 1 FROM telemetry_sent t WHERE t.event_id = e.id)
                    ORDER BY e.at, e.id LIMIT ?
                    """, arguments: [since, max(0, limit)]
            ).map { row in try EventRow(row: row) }
        }
    }

    /// Records that a batch was accepted (or refused with a 4xx, which is never retried). Events themselves are
    /// never updated; an ID already recorded keeps its first batch.
    public func markTelemetrySent(eventIDs: [String], batchID: String, at: Int64) async throws(StorageError) {
        try await write { db in
            try db.inTransaction {
                let insert = try db.cachedStatement(
                    sql: """
                        INSERT INTO telemetry_sent (event_id, batch_id, sent_at) VALUES (?, ?, ?)
                        ON CONFLICT(event_id) DO NOTHING
                        """)
                for id in eventIDs { try insert.execute(arguments: [id.lowercased(), batchID, at]) }
                return .commit
            }
        }
    }
}
