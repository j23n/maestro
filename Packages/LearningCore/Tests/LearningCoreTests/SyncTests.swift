import Foundation
import Testing

@testable import LearningCore

/// docs/08 § Merge rules, § CloudKit layout, § Settings.
@Suite struct MergeRulesTests {
    func event(_ id: String, at: Int64 = 1, device: String = "a") -> Event {
        Event(id: id, at: at, tzOffsetMin: 0, deviceId: device, packVersion: "0.1.0",
              payload: .stepStarted(StepEventPayload(stepId: "u00.step-opener", sessionId: "s")))
    }

    @Test func eventsAreInsertedIfAbsentAndNeverUpdated() {
        var log: [String: Event] = [:]
        let a = event("00000000-0000-4000-8000-00000000000a")
        let b = event("00000000-0000-4000-8000-00000000000b")
        #expect(MergeRules.insert([a, b, a], into: &log).map(\.id) == [a.id, b.id])
        #expect(log.values.allSatisfy { $0.origin == .remote })
        var changed = a
        changed.at = 99
        #expect(MergeRules.insert([changed], into: &log).isEmpty)
        #expect(log[a.id]?.at == 1)
        #expect(MergeRules.newEvents([a, b], existingIDs: [a.id]).map(\.id) == [b.id])
    }

    func setting(_ value: JSONValue, at: Int64, device: String, key: SettingKey = .goalDaysPerWeek) -> SettingRecord {
        SettingRecord(key, value: value, updatedAt: at, deviceId: device)
    }

    @Test func settingsAreLastWriterWinsWithTiesToTheLargerDeviceID() {
        let old = setting(.number(3), at: 100, device: "zz-phone")
        let new = setting(.number(4), at: 200, device: "aa-mac")
        #expect(MergeRules.wins(new, over: old))
        #expect(!MergeRules.wins(old, over: new))
        let tieA = setting(.number(5), at: 300, device: "ipad-A")
        let tieB = setting(.number(6), at: 300, device: "ipad-B")
        #expect(MergeRules.wins(tieB, over: tieA))
        #expect(!MergeRules.wins(tieA, over: tieB))
        // A full tie (never expected) still resolves the same way on every device.
        let x = setting(.number(1), at: 1, device: "d")
        let y = setting(.number(2), at: 1, device: "d")
        #expect(MergeRules.wins(y, over: x) != MergeRules.wins(x, over: y))
        #expect(MergeRules.resolve(local: old, remote: new) == .takeRemote)
        #expect(MergeRules.resolve(local: new, remote: old) == .keepLocal)
        #expect(MergeRules.resolve(local: nil, remote: old) == .takeRemote)
    }

    @Test func deviceSettingsNeverSync() {
        let remote = SettingRecord(.speechEnabled, value: .bool(false), updatedAt: 999, deviceId: "other")
        #expect(MergeRules.resolve(local: nil, remote: remote) == .keepLocal)
        let scale = SettingRecord(.displayTextScale, value: .number(1.4), updatedAt: 999, deviceId: "other")
        #expect(scale.scope == .device)
        #expect(MergeRules.resolve(local: nil, remote: scale) == .keepLocal)
        #expect(throws: RecordMappingError.notSynced("display.textScale")) { try RecordMapping.record(for: scale) }
    }

    @Test(arguments: 0..<50)
    func settingsConvergeWhateverTheOrder(seed: Int) {
        var rng = SplitMix64(seedString: "settings-\(seed)")
        var writes: [SettingRecord] = []
        for _ in 0..<12 {
            let key: SettingKey = [.goalDaysPerWeek, .profileName, .reviewDailyLimit][rng.nextInt(below: 3)]
            let device = ["iphone", "ipad", "mac"][rng.nextInt(below: 3)]
            writes.append(SettingRecord(key, value: .number(Double(rng.nextInt(below: 9))),
                                        updatedAt: Int64(rng.nextInt(below: 5)), deviceId: device))
        }
        var tables: [[String: SettingRecord]] = []
        for order in 0..<4 {
            var table: [String: SettingRecord] = [:]
            var orderRng = SplitMix64(seedString: "o-\(seed)-\(order)")
            for record in (writes + writes.prefix(3)).seededShuffle(using: &orderRng) {
                MergeRules.apply(record, to: &table)
            }
            tables.append(table)
        }
        #expect(tables.allSatisfy { $0 == tables[0] })
        #expect(LearnerSettings(records: writes).records == tables[0])
    }
}

@Suite struct RecordMappingTests {
    @Test func eventRecordsUseTheDocFieldNames() throws {
        let event = Event(id: "6F1C2E4A-0000-4000-8000-000000000001", at: 1_791_360_000_000, tzOffsetMin: -300,
                          deviceId: "iphone-1", packVersion: "0.6.0",
                          payload: .glossTapped(GlossTappedPayload(textId: "u02.l1.story", line: 3, token: 1)))
        let record = try RecordMapping.record(for: event)
        #expect(record.recordType == .event)
        #expect(record.recordType.rawValue == "Event")
        #expect(record.recordName == "6f1c2e4a-0000-4000-8000-000000000001")
        #expect(Set(record.fields.keys) == ["type", "at", "tzOffsetMin", "deviceId", "schema", "packVersion",
                                            "payload"])
        #expect(record.fields["type"] == .string("glossTapped"))
        #expect(record.fields["at"] == .int64(1_791_360_000_000))
        #expect(record.fields["tzOffsetMin"] == .int64(-300))
        #expect(record.fields["schema"] == .int64(1))
        #expect(record.fields["payload"] == .bytes(Data(#"{"line":3,"textId":"u02.l1.story","token":1}"#.utf8)))
        var back = try RecordMapping.event(from: record)
        #expect(back.origin == .remote)
        back.origin = .local
        #expect(back == event)
        #expect(RecordMapping.recordType(forRecordName: record.recordName) == .event)
    }

    @Test func unknownEventTypesSurviveTheRoundTrip() throws {
        let raw = Data(#"{"x":[1,2]}"#.utf8)
        let event = Event(id: "00000000-0000-4000-8000-0000000000ff", at: 1, tzOffsetMin: 0, deviceId: "mac",
                          packVersion: "0.9.0", payload: .unknown(type: "hint2", json: raw))
        let back = try RecordMapping.event(from: RecordMapping.record(for: event))
        #expect(back.payload == .unknown(type: "hint2", json: raw))
    }

    @Test func settingRecords() throws {
        let consent = StudyConsent(version: "v1", date: 1_791_360_000_000, granted: true)
        let setting = SettingRecord(.studyConsent, value: consent.json, updatedAt: 42, deviceId: "ipad")
        let record = try RecordMapping.record(for: setting)
        #expect(record.recordType.rawValue == "Setting")
        #expect(record.recordName == "setting.study.consent")
        #expect(Set(record.fields.keys) == ["value", "updatedAt", "deviceId"])
        #expect(record.fields["value"]
                == .bytes(Data(#"{"date":1791360000000,"granted":true,"version":"v1"}"#.utf8)))
        let back = try RecordMapping.setting(from: record)
        #expect(back == setting)
        #expect(StudyConsent(json: back.value) == consent)
        #expect(RecordMapping.settingKey(fromRecordName: "setting.goal.daysPerWeek") == "goal.daysPerWeek")
        #expect(RecordMapping.recordType(forRecordName: "setting.goal.daysPerWeek") == .setting)
    }

    @Test func malformedRecordsAreRejected() {
        let bad = SyncRecord(recordType: .event, recordName: "not-a-uuid", fields: [:])
        #expect(throws: RecordMappingError.badRecordName("not-a-uuid")) { try RecordMapping.event(from: bad) }
        let missing = SyncRecord(recordType: .event, recordName: "00000000-0000-4000-8000-000000000001",
                                 fields: ["type": .string("session")])
        #expect(throws: RecordMappingError.missingField("payload")) { try RecordMapping.event(from: missing) }
        let wrong = SyncRecord(recordType: .setting, recordName: "setting.x", fields: [:])
        #expect(throws: RecordMappingError.wrongRecordType(expected: "Event", got: "Setting")) {
            try RecordMapping.event(from: wrong)
        }
        let json = SyncRecord(recordType: .setting, recordName: "setting.x", fields: [
            "value": .bytes(Data("{".utf8)), "updatedAt": .int64(1), "deviceId": .string("d"),
        ])
        #expect(throws: RecordMappingError.invalidJSON("value")) { try RecordMapping.setting(from: json) }
    }
}

@Suite struct SettingsTests {
    @Test func everyKeyWithItsScopeAndDefault() {
        let expected: [String: (SettingScope, JSONValue?)] = [
            "profile.name": (.synced, .string("")),
            "profile.forms": (.synced, .string("both")),
            "profile.country": (.synced, nil),
            "profile.reason": (.synced, nil),
            "goal.daysPerWeek": (.synced, .number(5)),
            "review.dailyLimit": (.synced, .number(60)),
            "display.englishUnderStories": (.synced, .bool(false)),
            "display.textScale": (.device, .number(1)),
            "display.speakerLabels": (.synced, nil),
            "audio.storyRate": (.synced, .number(1)),
            "mascot.hints": (.synced, .bool(true)),
            "answers.strictForms": (.synced, .bool(false)),
            "study.consent": (.synced, nil),
            "study.installId": (.synced, nil),
            "speech.enabled": (.device, nil),
            "reminder.enabled": (.device, .bool(false)),
            "reminder.time": (.device, nil),
            "sync.paused": (.device, .bool(false)),
        ]
        #expect(Set(SettingKey.allCases.map(\.rawValue)) == Set(expected.keys))
        for key in SettingKey.allCases {
            #expect(key.scope == expected[key.rawValue]?.0, "\(key.rawValue)")
            #expect(key.defaultValue == expected[key.rawValue]?.1, "\(key.rawValue)")
        }
        #expect(SettingKey.scope(of: "future.key") == .synced)
    }

    @Test func typedDefaults() {
        let s = LearnerSettings()
        #expect(s.profileName == "")
        #expect(s.profileForms == .both)
        #expect(s.profileCountry == nil)
        #expect(s.goalDaysPerWeek == 5)
        #expect(s.reviewDailyLimit == 60)
        #expect(!s.englishUnderStories)
        #expect(s.textScale == 1)
        #expect(s.storyRate == 1)
        #expect(s.mascotHints)
        #expect(!s.strictForms)
        #expect(s.studyConsent == nil)
        #expect(s.studyInstallId == nil)
        #expect(!s.reminderEnabled)
        #expect(!s.syncPaused)
        // Speaker labels: on until Unit 5. Speech: on if available.
        #expect(s.speakerLabels(unitOrd: 4))
        #expect(!s.speakerLabels(unitOrd: 5))
        #expect(s.speechEnabled(available: true))
        #expect(!s.speechEnabled(available: false))
    }

    @Test func storedValuesWinAndWrongTypesFallBack() {
        var s = LearnerSettings(records: [
            SettingRecord(.profileForms, value: .string("f"), updatedAt: 1, deviceId: "a"),
            SettingRecord(.displayTextScale, value: .number(3), updatedAt: 1, deviceId: "a"),
            SettingRecord(.displaySpeakerLabels, value: .bool(false), updatedAt: 1, deviceId: "a"),
            SettingRecord(.goalDaysPerWeek, value: .string("lots"), updatedAt: 1, deviceId: "a"),
            SettingRecord(.speechEnabled, value: .bool(false), updatedAt: 1, deviceId: "a"),
        ])
        #expect(s.profileForms == .f)
        #expect(s.textScale == 1.6)  // clamped to 0.85…1.6
        #expect(!s.speakerLabels(unitOrd: 0))
        #expect(s.goalDaysPerWeek == 5)
        #expect(!s.speechEnabled(available: true))
        s.set(SettingRecord(.profileForms, value: .string("m"), updatedAt: 0, deviceId: "z"))
        #expect(s.profileForms == .f)  // older: ignored
        s.set(SettingRecord(.profileForms, value: .string("m"), updatedAt: 2, deviceId: "a"))
        #expect(s.profileForms == .m)
    }
}
