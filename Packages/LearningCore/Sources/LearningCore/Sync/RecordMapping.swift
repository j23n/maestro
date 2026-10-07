import Foundation

/// CloudKit record types (docs/08 § CloudKit layout).
public enum SyncRecordType: String, Sendable {
    case event = "Event"
    case setting = "Setting"
}

/// A CloudKit field value, without CloudKit.
public enum RecordFieldValue: Hashable, Sendable {
    case string(String)
    case int64(Int64)
    case bytes(Data)
}

/// A CloudKit-agnostic record: the App's `CloudSync` maps it to and from `CKRecord` field by field.
public struct SyncRecord: Hashable, Sendable {
    public var recordType: SyncRecordType
    public var recordName: String
    public var fields: [String: RecordFieldValue]

    public init(recordType: SyncRecordType, recordName: String, fields: [String: RecordFieldValue]) {
        self.recordType = recordType
        self.recordName = recordName
        self.fields = fields
    }
}

public enum RecordMappingError: Error, Equatable, Sendable {
    case wrongRecordType(expected: String, got: String)
    case missingField(String)
    case badRecordName(String)
    case invalidJSON(String)
    case notSynced(String)
}

/// Events and settings ↔ records, field names exactly as docs/08 § CloudKit layout:
///
/// - `Event`, record name the event UUID (lowercase): `type` String, `at` Int64, `tzOffsetMin` Int64, `deviceId`
///   String, `schema` Int64, `packVersion` String, `payload` Bytes (UTF-8 JSON).
/// - `Setting`, record name `setting.<key>`: `value` Bytes (JSON), `updatedAt` Int64, `deviceId` String.
public enum RecordMapping {
    /// The one custom zone in the private database.
    public static let zoneName = "Learner"
    public static let settingRecordPrefix = "setting."

    public enum EventField {
        public static let type = "type"
        public static let at = "at"
        public static let tzOffsetMin = "tzOffsetMin"
        public static let deviceId = "deviceId"
        public static let schema = "schema"
        public static let packVersion = "packVersion"
        public static let payload = "payload"
    }

    public enum SettingField {
        public static let value = "value"
        public static let updatedAt = "updatedAt"
        public static let deviceId = "deviceId"
    }

    // MARK: Record names

    public static func recordName(for event: Event) -> String { event.id.lowercased() }

    public static func recordName(forSettingKey key: String) -> String { settingRecordPrefix + key }

    /// The setting key of a `setting.<key>` record name, or nil for an event record name.
    public static func settingKey(fromRecordName name: String) -> String? {
        guard name.hasPrefix(settingRecordPrefix), name.count > settingRecordPrefix.count else { return nil }
        return String(name.dropFirst(settingRecordPrefix.count))
    }

    /// Which kind of row a pending record name (`sync_pending.record_name`) refers to.
    public static func recordType(forRecordName name: String) -> SyncRecordType {
        settingKey(fromRecordName: name) == nil ? .event : .setting
    }

    // MARK: Events

    public static func record(for event: Event) throws -> SyncRecord {
        SyncRecord(recordType: .event, recordName: recordName(for: event), fields: [
            EventField.type: .string(event.type),
            EventField.at: .int64(event.at),
            EventField.tzOffsetMin: .int64(Int64(event.tzOffsetMin)),
            EventField.deviceId: .string(event.deviceId),
            EventField.schema: .int64(Int64(event.schema)),
            EventField.packVersion: .string(event.packVersion),
            EventField.payload: .bytes(try EventCodec.encodePayload(event.payload)),
        ])
    }

    /// An event received from CloudKit (`origin` remote). Unknown types keep their payload untouched.
    public static func event(from record: SyncRecord) throws -> Event {
        guard record.recordType == .event else {
            throw RecordMappingError.wrongRecordType(expected: SyncRecordType.event.rawValue,
                                                     got: record.recordType.rawValue)
        }
        let name = record.recordName.lowercased()
        guard UUID(uuidString: name) != nil else { throw RecordMappingError.badRecordName(record.recordName) }
        let payload = try bytes(record, EventField.payload)
        return Event(id: name, at: try int64(record, EventField.at),
                     tzOffsetMin: Int(try int64(record, EventField.tzOffsetMin)),
                     deviceId: try string(record, EventField.deviceId),
                     schema: Int(try int64(record, EventField.schema)),
                     packVersion: try string(record, EventField.packVersion),
                     payload: EventCodec.decodePayload(type: try string(record, EventField.type), json: payload),
                     origin: .remote)
    }

    // MARK: Settings

    /// The record for a synced setting; device-scoped settings never sync.
    public static func record(for setting: SettingRecord) throws -> SyncRecord {
        guard setting.scope == .synced else { throw RecordMappingError.notSynced(setting.key) }
        return SyncRecord(recordType: .setting, recordName: recordName(forSettingKey: setting.key), fields: [
            SettingField.value: .bytes(try setting.valueJSON()),
            SettingField.updatedAt: .int64(setting.updatedAt),
            SettingField.deviceId: .string(setting.deviceId),
        ])
    }

    public static func setting(from record: SyncRecord) throws -> SettingRecord {
        guard record.recordType == .setting else {
            throw RecordMappingError.wrongRecordType(expected: SyncRecordType.setting.rawValue,
                                                     got: record.recordType.rawValue)
        }
        guard let key = settingKey(fromRecordName: record.recordName) else {
            throw RecordMappingError.badRecordName(record.recordName)
        }
        let json = try bytes(record, SettingField.value)
        guard let value = try? JSONDecoder().decode(JSONValue.self, from: json) else {
            throw RecordMappingError.invalidJSON(SettingField.value)
        }
        return SettingRecord(key: key, value: value, updatedAt: try int64(record, SettingField.updatedAt),
                             deviceId: try string(record, SettingField.deviceId))
    }

    // MARK: Field access

    static func string(_ record: SyncRecord, _ field: String) throws -> String {
        guard case .string(let s)? = record.fields[field] else { throw RecordMappingError.missingField(field) }
        return s
    }

    static func int64(_ record: SyncRecord, _ field: String) throws -> Int64 {
        guard case .int64(let n)? = record.fields[field] else { throw RecordMappingError.missingField(field) }
        return n
    }

    static func bytes(_ record: SyncRecord, _ field: String) throws -> Data {
        guard case .bytes(let d)? = record.fields[field] else { throw RecordMappingError.missingField(field) }
        return d
    }
}
