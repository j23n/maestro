import Foundation
import GRDB
import LearningCore

/// One `events` row as stored (docs/03 § The learner database). `payload` is the JSON text exactly as it was written
/// (this device's canonical encoding) or received (another device's bytes, kept as they came), so fields a newer
/// client added survive a re-upload and reach telemetry untouched.
public struct EventRow: Sendable, Hashable {
    public var id: String
    /// Milliseconds since the epoch, UTC.
    public var at: Int64
    public var tzOffsetMin: Int
    public var type: String
    public var deviceId: String
    public var schema: Int
    public var packVersion: String
    /// The payload JSON (UTF-8 text).
    public var payload: String
    public var origin: EventOrigin

    public init(
        id: String, at: Int64, tzOffsetMin: Int, type: String, deviceId: String, schema: Int,
        packVersion: String, payload: String, origin: EventOrigin
    ) {
        self.id = id.lowercased()
        self.at = at
        self.tzOffsetMin = tzOffsetMin
        self.type = type
        self.deviceId = deviceId
        self.schema = schema
        self.packVersion = packVersion
        self.payload = payload
        self.origin = origin
    }

    /// The row of a typed event, with its canonical payload JSON. `origin` overrides the event's own.
    public init(_ event: Event, origin: EventOrigin? = nil) throws(StorageError) {
        let payload: String
        do {
            payload = try EventCodec.payloadString(event.payload)
        } catch {
            throw .invalidValue(table: "events", id: event.id, reason: "payload doesn't encode as JSON: \(error)")
        }
        self.init(
            id: event.id, at: event.at, tzOffsetMin: event.tzOffsetMin, type: event.type,
            deviceId: event.deviceId, schema: event.schema, packVersion: event.packVersion, payload: payload,
            origin: origin ?? event.origin)
    }

    /// The typed event. An unknown type, or a payload this version can't decode, becomes `.unknown` with the raw
    /// JSON, which replay ignores (docs/05 § Events).
    public var event: Event {
        EventCodec.event(
            id: id, at: at, tzOffsetMin: tzOffsetMin, type: type, deviceId: deviceId, schema: schema,
            packVersion: packVersion, payload: payload, origin: origin)
    }

    public var key: EventKey { EventKey(at: at, id: id) }

    // MARK: SQL

    static let columns = "id, at, tz_offset_min, type, device_id, schema, pack_version, payload, origin"

    /// Reads the columns in `columns` order.
    init(row: Row) throws(StorageError) {
        let id: String = (try? row.decode(String.self, atIndex: 0)) ?? "?"
        do {
            let originRaw = try row.decode(String.self, atIndex: 8)
            guard let origin = EventOrigin(rawValue: originRaw) else {
                throw StorageError.invalidValue(table: "events", id: id, reason: "unknown origin \(originRaw)")
            }
            self.init(
                id: id, at: try row.decode(Int64.self, atIndex: 1),
                tzOffsetMin: try row.decode(Int.self, atIndex: 2), type: try row.decode(String.self, atIndex: 3),
                deviceId: try row.decode(String.self, atIndex: 4), schema: try row.decode(Int.self, atIndex: 5),
                packVersion: try row.decode(String.self, atIndex: 6),
                payload: try row.decode(String.self, atIndex: 7), origin: origin)
        } catch let error as StorageError {
            throw error
        } catch {
            throw .invalidValue(table: "events", id: id, reason: "\(error)")
        }
    }

    var arguments: StatementArguments {
        [id, at, tzOffsetMin, type, deviceId, schema, packVersion, payload, origin.rawValue]
    }
}
