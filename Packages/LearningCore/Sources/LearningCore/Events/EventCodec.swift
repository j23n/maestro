import Foundation

/// Any JSON value, for payloads this version can't type (unknown event types) and for settings values.
public enum JSONValue: Hashable, Sendable, Codable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() {
            self = .null
        } else if let b = try? c.decode(Bool.self) {
            self = .bool(b)
        } else if let n = try? c.decode(Double.self) {
            self = .number(n)
        } else if let s = try? c.decode(String.self) {
            self = .string(s)
        } else if let a = try? c.decode([JSONValue].self) {
            self = .array(a)
        } else {
            self = .object(try c.decode([String: JSONValue].self))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let b): try c.encode(b)
        case .number(let n): try c.encode(n)
        case .string(let s): try c.encode(s)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        }
    }
}

public enum EventCodecError: Error, Equatable {
    case missingField(String)
    case invalidJSON
}

/// JSON for events: payloads as stored in `events.payload` and CloudKit's `payload` field, and whole envelopes
/// (fixtures, debugging). Encoding is deterministic: sorted keys, no whitespace, nil fields omitted.
public enum EventCodec {
    static func makeEncoder() -> JSONEncoder {
        let e = JSONEncoder()
        e.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return e
    }

    /// Canonical payload JSON (sorted keys). Unknown payloads are returned exactly as they were received.
    public static func encodePayload(_ payload: EventPayload) throws -> Data {
        let e = makeEncoder()
        switch payload {
        case .introduced(let p): return try e.encode(p)
        case .attempt(let p): return try e.encode(p)
        case .stepStarted(let p), .stepCompleted(let p): return try e.encode(p)
        case .glossTapped(let p): return try e.encode(p)
        case .audioPlayed(let p): return try e.encode(p)
        case .session(let p): return try e.encode(p)
        case .checkCompleted(let p): return try e.encode(p)
        case .placementCompleted(let p): return try e.encode(p)
        case .onboardingCompleted(let p): return try e.encode(p)
        case .unknown(_, let json): return json
        }
    }

    /// The payload JSON as a UTF-8 string (the `events.payload` column).
    public static func payloadString(_ payload: EventPayload) throws -> String {
        String(decoding: try encodePayload(payload), as: UTF8.self)
    }

    /// Decodes a stored payload. Never throws: an unknown type, or a payload this version can't decode, becomes
    /// `.unknown` with the raw JSON, which the reducer ignores (docs/05 § Events). Unknown keys are ignored.
    public static func decodePayload(type: String, json: Data) -> EventPayload {
        guard let known = EventType(rawValue: type) else { return .unknown(type: type, json: json) }
        let d = JSONDecoder()
        do {
            switch known {
            case .introduced: return .introduced(try d.decode(IntroducedPayload.self, from: json))
            case .attempt: return .attempt(try d.decode(AttemptPayload.self, from: json))
            case .stepStarted: return .stepStarted(try d.decode(StepEventPayload.self, from: json))
            case .stepCompleted: return .stepCompleted(try d.decode(StepEventPayload.self, from: json))
            case .glossTapped: return .glossTapped(try d.decode(GlossTappedPayload.self, from: json))
            case .audioPlayed: return .audioPlayed(try d.decode(AudioPlayedPayload.self, from: json))
            case .session: return .session(try d.decode(SessionPayload.self, from: json))
            case .checkCompleted: return .checkCompleted(try d.decode(CheckCompletedPayload.self, from: json))
            case .placementCompleted:
                return .placementCompleted(try d.decode(PlacementCompletedPayload.self, from: json))
            case .onboardingCompleted:
                return .onboardingCompleted(try d.decode(OnboardingCompletedPayload.self, from: json))
            }
        } catch {
            return .unknown(type: type, json: json)
        }
    }

    public static func decodePayload(type: String, json: String) -> EventPayload {
        decodePayload(type: type, json: Data(json.utf8))
    }

    /// Builds an event from the columns of an `events` row.
    public static func event(id: String, at: Int64, tzOffsetMin: Int, type: String, deviceId: String, schema: Int,
                             packVersion: String, payload: String, origin: EventOrigin) -> Event
    {
        Event(id: id, at: at, tzOffsetMin: tzOffsetMin, deviceId: deviceId, schema: schema, packVersion: packVersion,
              payload: decodePayload(type: type, json: payload), origin: origin)
    }

    /// The whole envelope as camelCase JSON with the payload nested as an object.
    public static func encodeEnvelope(_ event: Event) throws -> Data {
        try makeEncoder().encode(event)
    }

    public static func decodeEnvelope(_ data: Data) throws -> Event {
        try JSONDecoder().decode(Event.self, from: data)
    }

    /// A JSON array of envelopes (the format of `fixtures/replay/*.json` event lists).
    public static func encodeLog(_ events: [Event]) throws -> Data {
        try makeEncoder().encode(events)
    }

    public static func decodeLog(_ data: Data) throws -> [Event] {
        try JSONDecoder().decode([Event].self, from: data)
    }
}

extension Event: Codable {
    enum CodingKeys: String, CodingKey {
        case id, at, tzOffsetMin, type, deviceId, schema, packVersion, payload, origin
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let type = try c.decode(String.self, forKey: .type)
        let payload: EventPayload
        if let known = EventType(rawValue: type), let typed = try? Self.decodeKnown(known, from: c) {
            payload = typed
        } else {
            let raw = try c.decode(JSONValue.self, forKey: .payload)
            payload = .unknown(type: type, json: try EventCodec.makeEncoder().encode(raw))
        }
        self.init(id: try c.decode(String.self, forKey: .id), at: try c.decode(Int64.self, forKey: .at),
                  tzOffsetMin: try c.decode(Int.self, forKey: .tzOffsetMin),
                  deviceId: try c.decode(String.self, forKey: .deviceId),
                  schema: try c.decodeIfPresent(Int.self, forKey: .schema) ?? Event.currentSchema,
                  packVersion: try c.decodeIfPresent(String.self, forKey: .packVersion) ?? "",
                  payload: payload,
                  origin: try c.decodeIfPresent(EventOrigin.self, forKey: .origin) ?? .local)
    }

    private static func decodeKnown(_ type: EventType, from c: KeyedDecodingContainer<CodingKeys>) throws
        -> EventPayload
    {
        switch type {
        case .introduced: .introduced(try c.decode(IntroducedPayload.self, forKey: .payload))
        case .attempt: .attempt(try c.decode(AttemptPayload.self, forKey: .payload))
        case .stepStarted: .stepStarted(try c.decode(StepEventPayload.self, forKey: .payload))
        case .stepCompleted: .stepCompleted(try c.decode(StepEventPayload.self, forKey: .payload))
        case .glossTapped: .glossTapped(try c.decode(GlossTappedPayload.self, forKey: .payload))
        case .audioPlayed: .audioPlayed(try c.decode(AudioPlayedPayload.self, forKey: .payload))
        case .session: .session(try c.decode(SessionPayload.self, forKey: .payload))
        case .checkCompleted: .checkCompleted(try c.decode(CheckCompletedPayload.self, forKey: .payload))
        case .placementCompleted: .placementCompleted(try c.decode(PlacementCompletedPayload.self, forKey: .payload))
        case .onboardingCompleted:
            .onboardingCompleted(try c.decode(OnboardingCompletedPayload.self, forKey: .payload))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(at, forKey: .at)
        try c.encode(tzOffsetMin, forKey: .tzOffsetMin)
        try c.encode(type, forKey: .type)
        try c.encode(deviceId, forKey: .deviceId)
        try c.encode(schema, forKey: .schema)
        try c.encode(packVersion, forKey: .packVersion)
        switch payload {
        case .introduced(let p): try c.encode(p, forKey: .payload)
        case .attempt(let p): try c.encode(p, forKey: .payload)
        case .stepStarted(let p), .stepCompleted(let p): try c.encode(p, forKey: .payload)
        case .glossTapped(let p): try c.encode(p, forKey: .payload)
        case .audioPlayed(let p): try c.encode(p, forKey: .payload)
        case .session(let p): try c.encode(p, forKey: .payload)
        case .checkCompleted(let p): try c.encode(p, forKey: .payload)
        case .placementCompleted(let p): try c.encode(p, forKey: .payload)
        case .onboardingCompleted(let p): try c.encode(p, forKey: .payload)
        case .unknown(_, let json): try c.encode(try JSONDecoder().decode(JSONValue.self, from: json), forKey: .payload)
        }
        try c.encode(origin, forKey: .origin)
    }
}
