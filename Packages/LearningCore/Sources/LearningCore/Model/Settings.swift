import Foundation

/// Synced settings follow the learner across devices; device settings never leave the device (docs/08 § Settings).
public enum SettingScope: String, Codable, Sendable {
    case synced, device
}

/// Every setting key of docs/08 § Settings, with its scope and default.
public enum SettingKey: String, CaseIterable, Codable, Sendable {
    case profileName = "profile.name"
    case profileForms = "profile.forms"
    case profileCountry = "profile.country"
    case profileReason = "profile.reason"
    case goalDaysPerWeek = "goal.daysPerWeek"
    case reviewDailyLimit = "review.dailyLimit"
    case displayEnglishUnderStories = "display.englishUnderStories"
    case displayTextScale = "display.textScale"
    case displaySpeakerLabels = "display.speakerLabels"
    case audioStoryRate = "audio.storyRate"
    case mascotHints = "mascot.hints"
    case answersStrictForms = "answers.strictForms"
    case studyConsent = "study.consent"
    case studyInstallId = "study.installId"
    case speechEnabled = "speech.enabled"
    case reminderEnabled = "reminder.enabled"
    case reminderTime = "reminder.time"
    case syncPaused = "sync.paused"

    /// `display.textScale` is device-scoped: text size is a per-device preference (bigger on an iPhone, normal
    /// on a Mac).
    public var scope: SettingScope {
        switch self {
        case .displayTextScale, .speechEnabled, .reminderEnabled, .reminderTime, .syncPaused: .device
        default: .synced
        }
    }

    /// The default value, or nil for "not set" and for defaults that depend on context (`display.speakerLabels`:
    /// true until Unit 5; `speech.enabled`: true if speech is available; see `LearnerSettings`).
    public var defaultValue: JSONValue? {
        switch self {
        case .profileName: .string("")
        case .profileForms: .string(LearnerForms.both.rawValue)
        case .goalDaysPerWeek: .number(5)
        case .reviewDailyLimit: .number(60)
        case .displayEnglishUnderStories: .bool(false)
        case .displayTextScale: .number(1.0)
        case .audioStoryRate: .number(1.0)
        case .mascotHints: .bool(true)
        case .answersStrictForms: .bool(false)
        case .reminderEnabled: .bool(false)
        case .syncPaused: .bool(false)
        case .profileCountry, .profileReason, .studyConsent, .studyInstallId, .displaySpeakerLabels,
            .speechEnabled, .reminderTime:
            nil
        }
    }

    /// The scope of any key, including keys from newer clients (synced).
    public static func scope(of key: String) -> SettingScope {
        SettingKey(rawValue: key)?.scope ?? .synced
    }
}

/// One `settings` row: per-key last-writer-wins by `(updatedAt, deviceId)`.
public struct SettingRecord: Codable, Hashable, Sendable {
    /// The key as stored (`SettingKey.rawValue`, or a newer client's key).
    public var key: String
    public var value: JSONValue
    /// Milliseconds since the epoch.
    public var updatedAt: Int64
    public var deviceId: String
    public var scope: SettingScope

    public init(key: String, value: JSONValue, updatedAt: Int64, deviceId: String, scope: SettingScope? = nil) {
        self.key = key
        self.value = value
        self.updatedAt = updatedAt
        self.deviceId = deviceId
        self.scope = scope ?? SettingKey.scope(of: key)
    }

    public init(_ key: SettingKey, value: JSONValue, updatedAt: Int64, deviceId: String) {
        self.init(key: key.rawValue, value: value, updatedAt: updatedAt, deviceId: deviceId, scope: key.scope)
    }

    /// The value as canonical JSON (the `value` column and CloudKit's `value` field).
    public func valueJSON() throws -> Data { try EventCodec.makeEncoder().encode(value) }
}

/// `study.consent = {version, date, granted}` (docs/12): the consent text version and the date in milliseconds.
public struct StudyConsent: Hashable, Sendable {
    public var version: String
    public var date: Int64
    public var granted: Bool

    public init(version: String, date: Int64, granted: Bool) {
        self.version = version
        self.date = date
        self.granted = granted
    }

    public init?(json: JSONValue) {
        guard case .object(let o) = json, case .string(let version)? = o["version"],
            case .number(let date)? = o["date"], case .bool(let granted)? = o["granted"]
        else { return nil }
        self.init(version: version, date: Int64(date), granted: granted)
    }

    public var json: JSONValue {
        .object(["version": .string(version), "date": .number(Double(date)), "granted": .bool(granted)])
    }
}

/// A typed view over the stored setting records, falling back to the defaults (and to the default when a stored
/// value has the wrong type).
public struct LearnerSettings: Hashable, Sendable {
    public static let textScaleRange: ClosedRange<Double> = 0.85...1.6
    /// Speaker labels are on by default in Units 0–4.
    public static let speakerLabelsDefaultUntilUnitOrd = 5

    public private(set) var records: [String: SettingRecord]

    public init(records: [SettingRecord] = []) {
        var byKey: [String: SettingRecord] = [:]
        for record in records {
            if let current = byKey[record.key], !MergeRules.wins(record, over: current) { continue }
            byKey[record.key] = record
        }
        self.records = byKey
    }

    public func value(_ key: SettingKey) -> JSONValue? { records[key.rawValue]?.value ?? key.defaultValue }

    func string(_ key: SettingKey) -> String? {
        if case .string(let s)? = records[key.rawValue]?.value { return s }
        if case .string(let s)? = key.defaultValue { return s }
        return nil
    }

    func bool(_ key: SettingKey) -> Bool? {
        if case .bool(let b)? = records[key.rawValue]?.value { return b }
        if case .bool(let b)? = key.defaultValue { return b }
        return nil
    }

    func number(_ key: SettingKey) -> Double? {
        if case .number(let n)? = records[key.rawValue]?.value, n.isFinite { return n }
        if case .number(let n)? = key.defaultValue { return n }
        return nil
    }

    public var profileName: String { string(.profileName) ?? "" }
    public var profileForms: LearnerForms { string(.profileForms).flatMap(LearnerForms.init(rawValue:)) ?? .both }
    public var profileCountry: String? { string(.profileCountry) }
    public var profileReason: String? { string(.profileReason) }
    public var goalDaysPerWeek: Int { Int(number(.goalDaysPerWeek) ?? 5) }
    public var reviewDailyLimit: Int { Int(number(.reviewDailyLimit) ?? 60) }
    public var englishUnderStories: Bool { bool(.displayEnglishUnderStories) ?? false }
    public var textScale: Double {
        min(max(number(.displayTextScale) ?? 1, Self.textScaleRange.lowerBound), Self.textScaleRange.upperBound)
    }
    public var storyRate: Double { number(.audioStoryRate) ?? 1 }
    public var mascotHints: Bool { bool(.mascotHints) ?? true }
    public var strictForms: Bool { bool(.answersStrictForms) ?? false }
    public var studyConsent: StudyConsent? {
        records[SettingKey.studyConsent.rawValue].flatMap { StudyConsent(json: $0.value) }
    }
    public var studyInstallId: String? { string(.studyInstallId) }
    public var reminderEnabled: Bool { bool(.reminderEnabled) ?? false }
    public var reminderTime: String? { string(.reminderTime) }
    public var syncPaused: Bool { bool(.syncPaused) ?? false }

    /// `display.speakerLabels`: the stored choice, else on in Units 0–4.
    public func speakerLabels(unitOrd: Int) -> Bool {
        bool(.displaySpeakerLabels) ?? (unitOrd < Self.speakerLabelsDefaultUntilUnitOrd)
    }

    /// `speech.enabled`: the stored choice (only meaningful when speech is available), else true if available.
    public func speechEnabled(available: Bool) -> Bool {
        available && (bool(.speechEnabled) ?? true)
    }

    /// Stores a change made on this device, if it wins over what is stored.
    public mutating func set(_ record: SettingRecord) {
        if let current = records[record.key], !MergeRules.wins(record, over: current) { return }
        records[record.key] = record
    }
}
