import Foundation
import GRDB
import LearningCore
import LearningCoreTestSupport
import Testing

@testable import Storage

/// docs/08 § Settings: device vs synced scope, last-writer-wins, pending uploads for synced keys only.
@Suite struct LearnerSettingsTests {
    @Test func defaultsBeforeAnythingIsStored() throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let settings = store.settings
        #expect(settings.records.isEmpty)
        #expect(settings.goalDaysPerWeek == 5)
        #expect(settings.reviewDailyLimit == 60)
        #expect(settings.textScale == 1.0)
        #expect(settings.profileForms == .both)
        #expect(settings.studyConsent == nil)
    }

    @Test func aSyncedChangeIsPendingAndADeviceChangeIsNot() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        let goal = try await store.set(.goalDaysPerWeek, to: .number(3))
        #expect(
            goal
                == SettingRecord(
                    .goalDaysPerWeek, value: .number(3), updatedAt: mondayNine,
                    deviceId: store.deviceId))
        db.clock.advance(byMs: 1_000)
        let scale = try await store.set(.displayTextScale, to: .number(1.25))
        #expect(scale.scope == .device)
        let consent = StudyConsent(version: "1", date: mondayNine, granted: true)
        try await store.set(.studyConsent, to: consent.json)

        #expect(store.settings.goalDaysPerWeek == 3)
        #expect(store.settings.textScale == 1.25)
        #expect(store.settings.studyConsent == consent)
        let pending = try await store.pendingChanges()
        #expect(pending.map(\.recordName) == ["setting.goal.daysPerWeek", "setting.study.consent"])
        #expect(pending.allSatisfy { $0.recordType == .setting })
        // Only synced settings become records.
        let record = try #require(try await store.syncRecord(named: "setting.goal.daysPerWeek"))
        #expect(try RecordMapping.setting(from: record) == goal)
        #expect(try await store.syncRecord(named: "setting.display.textScale") == nil)
        let scopes = try read(store) { db in
            try Row.fetchAll(db, sql: "SELECT key, scope FROM settings ORDER BY key").map {
                "\($0["key"] as String) \($0["scope"] as String)"
            }
        }
        #expect(scopes == ["display.textScale device", "goal.daysPerWeek synced", "study.consent synced"])
        try store.close()

        let reopened = try db.open()
        defer { try? reopened.close() }
        #expect(reopened.settings == store.settings)
    }

    @Test func remoteSettingsMergeByLastWriterWins() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let local = try await store.set(.reviewDailyLimit, to: .number(40))

        let older = SettingRecord(.reviewDailyLimit, value: .number(80), updatedAt: local.updatedAt - 1, deviceId: "zz")
        #expect(try await store.applyRemote(older) == .keepLocal)
        #expect(store.settings.reviewDailyLimit == 40)

        // A tie on updatedAt goes to the lexically larger deviceId.
        let tieSmaller = SettingRecord(
            .reviewDailyLimit, value: .number(70), updatedAt: local.updatedAt,
            deviceId: "0000")
        #expect(try await store.applyRemote(tieSmaller) == .keepLocal)
        let tieLarger = SettingRecord(
            .reviewDailyLimit, value: .number(70), updatedAt: local.updatedAt,
            deviceId: "ffff-device")
        #expect(try await store.applyRemote(tieLarger) == .takeRemote)
        #expect(store.settings.reviewDailyLimit == 70)

        let newer = SettingRecord(.reviewDailyLimit, value: .number(90), updatedAt: local.updatedAt + 5, deviceId: "a")
        #expect(try await store.applyRemote(newer) == .takeRemote)
        #expect(store.settings.reviewDailyLimit == 90)
        #expect(try await store.settingRecord(SettingKey.reviewDailyLimit.rawValue) == newer)
        // Taking a remote value doesn't make it pending again (only the local change is).
        #expect(try await store.pendingChanges().map(\.recordName) == ["setting.review.dailyLimit"])
        // A newer client's synced key is stored too.
        let future = SettingRecord(key: "lessons.autoplay", value: .bool(true), updatedAt: 1, deviceId: "a")
        #expect(try await store.applyRemote(future) == .takeRemote)
        #expect(store.settings.records["lessons.autoplay"]?.scope == .synced)
    }

    @Test func deviceScopedSettingsNeverComeFromOtherDevices() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let remote = SettingRecord(
            key: SettingKey.syncPaused.rawValue, value: .bool(true), updatedAt: mondayNine + 9,
            deviceId: "other", scope: .synced)
        #expect(try await store.applyRemote(remote) == .keepLocal)
        #expect(store.settings.syncPaused == false)
        #expect(try await store.settingRecord(SettingKey.syncPaused.rawValue) == nil)
    }

    @Test func aLocalChangeWinsOverAValueFromAClockThatRanAhead() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let ahead = SettingRecord(
            .audioStoryRate, value: .number(0.8), updatedAt: mondayNine + 3_600_000,
            deviceId: "ffff")
        try await store.applyRemote(ahead)
        let local = try await store.set(.audioStoryRate, to: .number(1.0))
        #expect(local.updatedAt == ahead.updatedAt + 1)
        #expect(store.settings.storyRate == 1.0)
        #expect(MergeRules.wins(local, over: ahead))
    }

    @Test func settingsUpdatesFollowEveryChange() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        var updates = store.settingsUpdates().makeAsyncIterator()
        #expect(await updates.next()?.mascotHints == true)
        try await store.set(.mascotHints, to: .bool(false))
        #expect(await updates.next()?.mascotHints == false)
        let remote = SettingRecord(.mascotHints, value: .bool(true), updatedAt: mondayNine + 60_000, deviceId: "b")
        try await store.applyRemote(remote)
        #expect(await updates.next()?.mascotHints == true)
    }
}

/// docs/08 § The sync engine: the bookkeeping `CloudSync` needs from Storage.
@Suite struct LearnerSyncBookkeepingTests {
    func events(_ db: TestLearnerDB, _ n: Int) -> [Event] {
        let factory = EventFactory(
            deviceId: "dev", packVersion: "0.1.0", clock: db.clock, ids: SeededUUIDSource(seed: "s"))
        return (0..<n).map { _ in factory.glossTapped(textId: TextID("u00.l1.story"), line: 1, token: 1, itemId: nil) }
    }

    @Test func pendingChangesComeAndGo() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let log = events(db, 3)
        try await store.append(log)
        db.clock.advance(byMs: 5_000)
        try await store.set(.profileName, to: .string("Sam"))
        #expect(try await store.pendingChanges().count == 4)

        try await store.removePending(recordNames: [log[0].id, "setting.profile.name"])
        #expect(Set(try await store.pendingChanges().map(\.recordName)) == [log[1].id, log[2].id])
        db.clock.advance(byMs: 5_000)
        try await store.addPending(recordNames: [log[0].id, log[1].id, "setting.profile.name"])
        let pending = try await store.pendingChanges()
        #expect(pending.count == 4)
        // log[1] kept its original time; the re-added ones are newer and typed from their names.
        #expect(pending.first { $0.recordName == log[1].id }?.addedAt == mondayNine)
        #expect(pending.first { $0.recordName == log[0].id }?.addedAt == mondayNine + 10_000)
        #expect(pending.first { $0.recordName == "setting.profile.name" }?.recordType == .setting)
    }

    @Test func eventRecordsMatchTheRecordMapping() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let event = events(db, 1)[0]
        try await store.append(event)
        let record = try #require(try await store.syncRecord(named: event.id))
        #expect(record == (try RecordMapping.record(for: event)))
        #expect(try RecordMapping.event(from: record).payload == event.payload)
        #expect(try await store.syncRecord(named: "8f0e0000-0000-4000-8000-000000000000") == nil)
        #expect(try await store.syncRecord(named: "setting.profile.name") == nil)
    }

    @Test func everythingCanBeMarkedPendingAgain() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let local = events(db, 2)
        try await store.append(local)
        let remote = EventFactory(
            deviceId: "pad", packVersion: "0.1.0", clock: db.clock,
            ids: SeededUUIDSource(seed: "pad")
        ).glossTapped(
            textId: "t", line: 1, token: 1,
            itemId: nil)
        try await store.insertRemote([remote])
        try await store.set(.goalDaysPerWeek, to: .number(4))
        try await store.set(.reminderEnabled, to: .bool(true))
        try await store.removePending(recordNames: try await store.pendingChanges().map(\.recordName))
        #expect(try await store.markEverythingPending() == 4)
        #expect(
            Set(try await store.pendingChanges().map(\.recordName))
                == Set(local.map(\.id) + [remote.id, "setting.goal.daysPerWeek"]))
    }

    @Test func engineStateAndSystemFieldsPersist() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        #expect(try await store.syncEngineState() == nil)
        try await store.saveSyncEngineState(Data([1, 2, 3]))
        try await store.saveSyncEngineState(Data([4]))
        #expect(try await store.syncEngineState() == Data([4]))
        try await store.saveSystemFields(Data([9]), recordName: "a")
        try await store.saveSystemFields(Data([8]), recordName: "b")
        try await store.removeSystemFields(recordNames: ["a"])
        #expect(try await store.systemFields(recordName: "a") == nil)
        #expect(try await store.systemFields(recordName: "b") == Data([8]))
        try store.close()
        let reopened = try db.open()
        defer { try? reopened.close() }
        #expect(try await reopened.syncEngineState() == Data([4]))
    }

    @Test func eraseProgressKeepsOnlyThisDevice() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        let log = SyntheticLearner.log(200)
        try await store.append(log)
        try await store.set(.profileName, to: .string("Sam"))
        try await store.set(.displayTextScale, to: .number(1.4))
        try await store.saveSyncEngineState(Data([7]))
        try await store.saveSystemFields(Data([1]), recordName: log[0].id)
        try await store.markTelemetrySent(eventIDs: [log[0].id], batchID: "b", at: 1)
        let deviceId = store.deviceId

        try await store.eraseProgress()
        let initial = Replay.initialState(content: TestCourse.standard)
        #expect(store.state == initial)
        for table in ["events", "sync_pending", "cloud_system_fields", "telemetry_sent", "memory", "introductions"] {
            #expect(try count(store, table) == 0, "\(table)")
        }
        #expect(store.settings.profileName == "")
        #expect(store.settings.textScale == 1.4)
        #expect(try await store.syncEngineState() == Data([7]))
        try store.close()

        let reopened = try db.open()
        defer { try? reopened.close() }
        #expect(reopened.deviceId == deviceId)
        #expect(reopened.launchRebuild == nil)
        #expect(reopened.state == initial)
    }
}

/// docs/12 § The endpoint contract (client): local events from the consent date that have no `telemetry_sent` row.
@Suite struct LearnerTelemetryTests {
    @Test func unsentLocalEventsFromTheConsentDateOldestFirst() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let factory = EventFactory(
            deviceId: store.deviceId, packVersion: "0.1.0", clock: db.clock,
            ids: SeededUUIDSource(seed: "t"))
        var local: [Event] = []
        for _ in 0..<6 {
            local.append(factory.glossTapped(textId: "u00.l1.story", line: 1, token: 1, itemId: nil))
            db.clock.advance(byMs: 60_000)
        }
        try await store.append(local)
        let remote = EventFactory(
            deviceId: "pad", packVersion: "0.1.0", clock: FixedClock(ms: mondayNine + 90_000),
            ids: SeededUUIDSource(seed: "pad")
        ).glossTapped(
            textId: "t", line: 1, token: 1,
            itemId: nil)
        try await store.insertRemote([remote])

        let consent = local[1].at
        let batch = try await store.unsentTelemetryEvents(since: consent, limit: 3)
        #expect(batch.map(\.id) == local[1...3].map(\.id))
        #expect(batch.allSatisfy { $0.origin == .local })
        #expect(batch[0].payload == (try EventCodec.payloadString(local[1].payload)))

        try await store.markTelemetrySent(eventIDs: batch.map(\.id), batchID: "batch-1", at: mondayNine + 1)
        #expect(try await store.unsentTelemetryEvents(since: consent, limit: 10).map(\.id) == local[4...5].map(\.id))
        // Marking again keeps the first batch; a rebuild never touches telemetry_sent.
        try await store.markTelemetrySent(eventIDs: [batch[0].id], batchID: "batch-2", at: mondayNine + 2)
        try await store.rebuildAll()
        let batches = try read(store) { db in
            try String.fetchAll(db, sql: "SELECT batch_id FROM telemetry_sent ORDER BY event_id")
        }
        #expect(batches == ["batch-1", "batch-1", "batch-1"])
        #expect(
            try await store.unsentTelemetryEvents(since: 0, limit: 10).map(\.id) == [local[0].id]
                + local[4...5]
                .map(\.id))
    }
}
