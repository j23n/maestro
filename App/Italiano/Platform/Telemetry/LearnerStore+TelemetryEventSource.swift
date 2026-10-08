import Foundation
import Storage

/// The learner store is the uploader's event source (docs/12 § The endpoint contract, task M6.5): local events from
/// the consent date without a `telemetry_sent` row, and the rows recorded after a 2xx or 4xx.
extension LearnerStore: TelemetryEventSource {
    func unsentLocalEvents(since: Int64, limit: Int) async throws -> [StoredEvent] {
        try await unsentTelemetryEvents(since: since, limit: limit).map(StoredEvent.init(row:))
    }

    func markSent(eventIDs: [String], batchID: String, at: Int64) async throws {
        try await markTelemetrySent(eventIDs: eventIDs, batchID: batchID, at: at)
    }
}

extension StoredEvent {
    init(row: EventRow) {
        self.init(
            id: row.id, at: row.at, tzOffsetMin: row.tzOffsetMin, type: row.type, schema: row.schema,
            packVersion: row.packVersion, payloadJSON: row.payload, isLocal: row.origin == .local)
    }
}
