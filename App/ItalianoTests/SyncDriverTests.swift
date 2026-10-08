import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// `SyncDriver` against the fake engine and in-memory private databases (docs/08 § The sync engine; tasks M7.2 and
/// M7.3): startup, state persistence, pending changes, batching, every `.sentRecordZoneChanges` branch, fetched
/// events and settings, zone deletion, Reset and pause. Runs on Linux (scripts/check-app-logic.sh --test).
@Suite struct SyncDriverTests {
    static func account(_ user: String = "_alice", cloud: FakeCloud = FakeCloud()) -> FakeICloud.Account {
        FakeICloud.Account(user: user, cloud: cloud)
    }

    // MARK: Startup, state, pending changes

    @Test func theFirstRunCreatesTheZoneAndUploadsWhatWasDoneOffline() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        let offline = try await device.lesson(outcomes: [.correct, .wrong])
        await device.driver.start()
        let engine = try #require(device.engine)
        #expect(engine.currentState.zoneSave)  // first run: `.saveZone(Learner)` is pending
        #expect(Set(engine.pendingSaves) == Set(offline.map(\.id)))  // reconciled from sync_pending

        try await device.sync()
        let cloud = try #require(device.cloud)
        #expect(cloud.hasZone)
        #expect(cloud.eventIDs == Set(offline.map(\.id)))
        #expect(try await device.pendingNames.isEmpty)
        #expect(try await device.store.syncAccount() == "_alice")
        let snapshot = await device.snapshot()
        #expect(snapshot?.status == .synced(atMs: device.clock.nowMs()))
        #expect(snapshot?.platforms == [.iPhone])
    }

    @Test func theStateSerializationIsSavedAndALaunchResumesFromIt() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        try await device.lesson(outcomes: [.correct])
        await device.driver.start()
        try await device.sync()
        let saved = try #require(try await device.store.syncEngineState())
        #expect(try JSONDecoder().decode(FakeEngine.State.self, from: saved) == device.engine?.currentState)

        try device.relaunch()
        await device.driver.start()
        let engine = try #require(device.engine)
        #expect(engine.currentState.token == (try JSONDecoder().decode(FakeEngine.State.self, from: saved)).token)
        #expect(!engine.currentState.zoneSave)  // not the first run any more
        #expect(engine.pendingSaves.isEmpty)
    }

    @Test func newLocalEventsAndSyncedSettingsReachTheEngineAfterTheirCommit() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        await device.driver.start()
        let engine = try #require(device.engine)
        let event = try await device.gloss()
        try await device.set(.goalDaysPerWeek, .number(3))
        try await device.set(.displayTextScale, .number(1.3))  // device-scoped: never pending
        #expect(await eventually { Set(engine.pendingSaves) == [event.id, "setting.goal.daysPerWeek"] })
    }

    /// docs/08 § Tests 2: killed between the append and `state.add`, the event is still uploaded after relaunch.
    @Test func aCrashBetweenAppendAndTheEngineIsRecoveredAtLaunch() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        await device.driver.start()
        try await device.sync()
        device.engine?.discard()  // dies before the handover
        let lost = try await device.gloss()
        try device.relaunch()
        await device.driver.start()
        #expect(device.engine?.pendingSaves == [lost.id])
        try await device.sync()
        #expect(device.cloud?.eventIDs.contains(lost.id) == true)
        #expect(try await device.pendingNames.isEmpty)
    }

    @Test func recordsWhoseRowsAreGoneAreDroppedFromTheEngineAndTheStore() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        await device.driver.start()
        let engine = try #require(device.engine)
        let missing = "0f0e0000-0000-4000-8000-0000000000aa"
        try await device.store.addPending(recordNames: [missing, "setting.display.textScale"])
        engine.addPendingSaves([missing, "setting.display.textScale"])
        let event = try await device.gloss()
        _ = try await device.settle()

        let records = await device.driver.recordsToSend(engine.pendingSaves, from: engine)
        #expect(records.map(\.record.recordName) == [event.id])
        #expect(records.first?.systemFields == nil)  // events always go up as new records
        #expect(engine.pendingSaves == [event.id])
        #expect(try await device.pendingNames == [event.id])
        // Another engine (a discarded one) gets nothing.
        let other = FakeEngine(state: .init(), icloud: device.icloud, driver: device.driver, seed: "other")
        #expect(await device.driver.recordsToSend([event.id], from: other).isEmpty)
    }

    /// Fetched events are inserted with one call at the end of the zone's fetch, and the state serialization
    /// saved for those batches waits until they are stored.
    @Test func aFetchIsInsertedOnceAndItsStateSavedAfterward() async throws {
        let shared = FakeCloud()
        let pad = try SyncTestDevice("pad", platform: .iPad, account: Self.account(cloud: shared))
        let phone = try SyncTestDevice("phone", account: Self.account(cloud: shared), fetchBatch: 3)
        await pad.driver.start()
        let sent = try await pad.lesson(outcomes: [.correct, .almost, .wrong, .correct])
        try await pad.sync()
        #expect(shared.eventIDs.count == sent.count)

        await phone.driver.start()
        let engine = try #require(phone.engine)
        let store = phone.store
        let observed = LogLines()
        engine.afterFetchedBatch = {
            let count = (try? await store.eventCount()) ?? -1
            let saved = (try? await store.syncEngineState()) != nil
            observed.log("\(count) \(saved)")
        }
        await phone.driver.syncNow()
        // Three batches of three: nothing inserted and no state saved until the fetch is over.
        #expect(observed.lines == ["0 false", "0 false", "0 false"])
        #expect(Set(try await phone.store.events().map(\.id)) == Set(sent.map(\.id)))
        let saved = try #require(try await phone.store.syncEngineState())
        #expect(try JSONDecoder().decode(FakeEngine.State.self, from: saved).token >= sent.count)
        #expect(phone.store.state == pad.store.state)
        #expect(await phone.snapshot()?.platforms == [.iPhone, .iPad])
    }

    @Test func aLongFetchIsInsertedInChunksOfTheLimit() async throws {
        let shared = FakeCloud()
        let pad = try SyncTestDevice("pad", platform: .iPad, account: Self.account(cloud: shared))
        let phone = try SyncTestDevice(
            "phone", account: Self.account(cloud: shared), fetchBatch: 2, insertBatchLimit: 4)
        await pad.driver.start()
        try await pad.lesson(outcomes: [.correct, .correct, .correct, .correct])
        try await pad.sync()
        await phone.driver.start()
        let store = phone.store
        let counts = LogLines()
        phone.engine?.afterFetchedBatch = { counts.log("\((try? await store.eventCount()) ?? -1)") }
        await phone.driver.syncNow()
        // Seven events in batches of two, stored four at a time and the rest at the end of the fetch.
        #expect(counts.lines == ["0", "4", "4", "4"])
        #expect(try await phone.store.eventCount() == 7)
    }

    // MARK: Save failures (docs/08 § `.sentRecordZoneChanges`)

    @Test func serverRecordChangedOnAnEventCountsAsSaved() async throws {
        let shared = FakeCloud()
        let pad = try SyncTestDevice("pad", account: Self.account(cloud: shared))
        await pad.driver.start()
        let event = try await pad.gloss()
        try await pad.sync()
        // The phone has the same event (from an earlier sync) and marks everything pending at its first sign-in.
        let phone = try SyncTestDevice("phone", account: Self.account(cloud: shared))
        try await phone.store.insertRemote([event])
        await phone.driver.start()
        let savesBefore = shared.savedCount
        try await phone.sync()
        #expect(shared.savedCount == savesBefore)
        #expect(try await phone.pendingNames.isEmpty)
        #expect(phone.engine?.pendingSaves.isEmpty == true)
    }

    @Test func aSettingConflictKeepsTheLastWriter() async throws {
        let shared = FakeCloud()
        let pad = try SyncTestDevice("pad", account: Self.account(cloud: shared))
        let phone = try SyncTestDevice("phone", account: Self.account(cloud: shared))
        await pad.driver.start()
        await phone.driver.start()
        try await pad.sync()
        try await phone.sync()

        // The phone writes later but uploads second without having fetched: conflict, the phone's value wins and
        // goes up again with the server's change tag.
        try await pad.set(.reviewDailyLimit, .number(40))
        phone.clock.set(ms: pad.clock.nowMs() + 60_000)
        let newer = try await phone.set(.reviewDailyLimit, .number(80))
        try await pad.sync()
        _ = try await phone.settle()
        let engine = try #require(phone.engine)
        try await engine.sendChanges()
        #expect(shared.setting(.reviewDailyLimit) == newer)
        #expect(try await phone.pendingNames.isEmpty)
        try await pad.sync()
        #expect(pad.store.settings.reviewDailyLimit == 80)

        // A Mac whose clock is behind writes without fetching: its upload loses, and it takes the server's value.
        let mac = try SyncTestDevice("mac", platform: .Mac, account: Self.account(cloud: shared))
        await mac.driver.start()
        mac.clock.set(ms: newer.updatedAt - 10_000)
        try await mac.set(.reviewDailyLimit, .number(20))
        _ = try await mac.settle()
        try await mac.engine?.sendChanges()
        #expect(shared.setting(.reviewDailyLimit) == newer)
        #expect(mac.store.settings.reviewDailyLimit == 80)
        #expect(try await mac.pendingNames.isEmpty)
        #expect(FakeCloud.tag(try await mac.store.systemFields(recordName: "setting.review.dailyLimit")) == 2)
    }

    @Test func aSettingThatChangedWhileItsUploadWasInFlightGoesUpAgain() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        await device.driver.start()
        try await device.sync()
        try await device.set(.audioStoryRate, .number(0.8))
        let engine = try #require(device.engine)
        let store = device.store
        engine.beforeSave = {
            engine.beforeSave = nil
            _ = try? await store.set(.audioStoryRate, to: .number(1.1))
        }
        try await device.sync()
        // The first save carried 0.8; 1.1 stayed pending and went up in the next batch.
        #expect(device.cloud?.setting(.audioStoryRate)?.value == .number(1.1))
        #expect(FakeCloud.tag(try await store.systemFields(recordName: "setting.audio.storyRate")) == 2)
        #expect(try await device.pendingNames.isEmpty)
    }

    @Test func zoneNotFoundRecreatesTheZoneAndSavesAgain() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        await device.driver.start()
        try await device.set(.goalDaysPerWeek, .number(4))
        try await device.sync()
        let cloud = try #require(device.cloud)
        cloud.dropZoneSilently()
        let event = try await device.gloss()
        try await device.set(.goalDaysPerWeek, .number(6))
        try await device.sync()
        #expect(cloud.hasZone)
        #expect(cloud.recordNames == [event.id, "setting.goal.daysPerWeek"])
        #expect(cloud.setting(.goalDaysPerWeek)?.value == .number(6))
        #expect(try await device.pendingNames.isEmpty)
    }

    @Test func unknownItemForgetsTheSystemFieldsAndSavesAgain() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        await device.driver.start()
        try await device.set(.mascotHints, .bool(false))
        try await device.sync()
        #expect(try await device.store.systemFields(recordName: "setting.mascot.hints") != nil)
        let cloud = try #require(device.cloud)
        cloud.dropRecordSilently("setting.mascot.hints")
        try await device.set(.mascotHints, .bool(true))
        try await device.sync()
        #expect(cloud.setting(.mascotHints)?.value == .bool(true))
        #expect(FakeCloud.tag(try await device.store.systemFields(recordName: "setting.mascot.hints")) == 1)
        #expect(try await device.pendingNames.isEmpty)
    }

    @Test func retryableFailuresStayPendingAndRefusalsPauseWithAReason() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        await device.driver.start()
        try await device.sync()
        let cloud = try #require(device.cloud)
        let busy = try await device.gloss()
        cloud.transientOnce = [busy.id]
        try await device.sync()
        #expect(cloud.eventIDs.contains(busy.id))  // retried within the same send

        let refused = try await device.gloss()
        cloud.refused = [refused.id]
        try await device.sync()
        #expect(await device.snapshot()?.status == .paused(.error))
        #expect(try await device.pendingNames == [refused.id])  // kept for the next launch
        #expect(device.engine?.pendingSaves.isEmpty == true)  // but no hot loop
        #expect(device.logs.lines.contains { $0.contains(refused.id) })

        cloud.refused = []
        cloud.quotaExceeded = true
        try await device.gloss()
        try await device.sync()
        #expect(await device.snapshot()?.status == .paused(.storageFull))

        cloud.quotaExceeded = false
        try device.relaunch()
        await device.driver.start()
        try await device.sync()
        #expect(try await device.pendingNames.isEmpty)
        #expect(await device.snapshot()?.status == .synced(atMs: device.clock.nowMs()))
    }

    @Test func noNetworkSaysWaitingAndRecovers() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        await device.driver.start()
        try await device.sync()
        let cloud = try #require(device.cloud)
        cloud.networkUp = false
        let event = try await device.gloss()
        try await device.sync()
        #expect(await device.snapshot()?.status == .waitingForNetwork)
        #expect(try await device.pendingNames == [event.id])

        cloud.networkUp = true
        await device.driver.networkChanged(available: false)
        #expect(await device.snapshot()?.status == .waitingForNetwork)
        await device.driver.networkChanged(available: true)
        device.clock.advance(byMs: 5_000)
        try await device.sync()
        #expect(await device.snapshot()?.status == .synced(atMs: device.clock.nowMs()))
        #expect(cloud.eventIDs.contains(event.id))
    }

    // MARK: Fetched settings, zone deletion, Reset

    @Test func fetchedSettingsMergeAndAWinningLocalValueGoesUpAgain() async throws {
        let shared = FakeCloud()
        let pad = try SyncTestDevice("pad", account: Self.account(cloud: shared))
        let phone = try SyncTestDevice("phone", account: Self.account(cloud: shared))
        await pad.driver.start()
        await phone.driver.start()
        let older = try await pad.set(.answersStrictForms, .bool(true))
        try await pad.sync()
        try await phone.sync()
        #expect(phone.store.settings.strictForms == true)
        #expect(FakeCloud.tag(try await phone.store.systemFields(recordName: "setting.answers.strictForms")) == 1)

        phone.clock.advance(byMs: 60_000)
        let local = try await phone.set(.answersStrictForms, .bool(false))
        try await phone.sync()
        #expect(shared.setting(.answersStrictForms) == local)

        // Another client overwrites it with an older value (it lost a conflict but saved anyway): the fetch keeps
        // the phone's value and sends it again, so the server converges on the winner.
        var stale = older
        stale.updatedAt = older.updatedAt + 1
        shared.overwrite(try RecordMapping.record(for: stale))
        // A device-scoped key from a confused client is neither taken nor sent back.
        let foreign = SettingRecord(
            key: SettingKey.displayTextScale.rawValue, value: .number(1.6), updatedAt: 1,
            deviceId: "zz", scope: .device)
        shared.overwrite(
            SyncRecord(
                recordType: .setting, recordName: "setting.display.textScale",
                fields: [
                    "value": .bytes(try foreign.valueJSON()), "updatedAt": .int64(1), "deviceId": .string("zz"),
                ]))
        try await phone.sync()
        #expect(phone.store.settings.strictForms == false)
        #expect(shared.setting(.answersStrictForms) == local)
        #expect(FakeCloud.tag(try await phone.store.systemFields(recordName: "setting.answers.strictForms")) == 4)
        #expect(phone.store.settings.textScale == 1.0)
        #expect(try await phone.pendingNames.isEmpty)
        #expect(phone.engine?.pendingSaves.isEmpty == true)
    }

    @Test func aZoneDeletedOnAnotherDeviceErasesProgressOnce() async throws {
        let shared = FakeCloud()
        let pad = try SyncTestDevice("pad", platform: .iPad, account: Self.account(cloud: shared))
        let phone = try SyncTestDevice("phone", account: Self.account(cloud: shared))
        await pad.driver.start()
        await phone.driver.start()
        try await pad.lesson(outcomes: [.correct])
        try await phone.lesson(outcomes: [.wrong])
        try await phone.set(.profileName, .string("Sam"))
        try await phone.set(.displayTextScale, .number(1.4))
        for device in [pad, phone, pad] { try await device.sync() }

        // Reset on the pad: its progress goes, the zone is deleted and recreated.
        await pad.driver.resetProgress()
        try await pad.sync()
        #expect(try await pad.store.eventCount() == 0)
        #expect(shared.hasZone)
        #expect(shared.recordNames.isEmpty)
        let afterReset = try await pad.gloss()
        try await pad.sync()
        try await pad.sync()  // its own deletion never erases it again
        #expect(try await pad.store.events().map(\.id) == [afterReset.id])
        #expect(await pad.snapshot()?.notice == nil)

        try await phone.sync()
        #expect(try await phone.store.events().map(\.id) == [afterReset.id])
        #expect(phone.store.settings.profileName == "")
        #expect(phone.store.settings.textScale == 1.4)  // device settings stay
        #expect(await phone.snapshot()?.notice == .progressResetElsewhere)
        await phone.driver.dismissNotice()
        #expect(await phone.snapshot()?.notice == nil)
        #expect(phone.store.state == pad.store.state)
    }

    @Test func aPurgedZoneErasesProgressAndIsRecreated() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        await device.driver.start()
        try await device.lesson(outcomes: [.correct])
        try await device.sync()
        let cloud = try #require(device.cloud)
        cloud.deleteZone(reason: .purged)
        try await device.sync()
        #expect(try await device.store.eventCount() == 0)
        #expect(cloud.hasZone)
        #expect(await device.snapshot()?.notice == .progressResetElsewhere)
    }

    @Test func anEncryptedDataResetUploadsEverythingAgain() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        await device.driver.start()
        let log = try await device.lesson(outcomes: [.correct, .wrong])
        try await device.set(.goalDaysPerWeek, .number(2))
        try await device.sync()
        let cloud = try #require(device.cloud)
        cloud.deleteZone(reason: .encryptedDataReset)
        try await device.sync()
        #expect(cloud.recordNames == Set(log.map(\.id) + ["setting.goal.daysPerWeek"]))
        #expect(try await device.store.eventCount() == log.count)
        #expect(try await device.pendingNames.isEmpty)
        #expect(await device.snapshot()?.notice == nil)
    }

    // MARK: Pause

    @Test func pausingReleasesTheEngineAndUnpausingPicksUpWhatCollected() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        await device.driver.start()
        try await device.sync()
        let first = try #require(device.engine)
        await device.driver.setPaused(true)
        #expect(first.isDiscarded)
        #expect(device.store.settings.syncPaused)
        let snapshot = await device.snapshot()
        #expect(snapshot?.status == .paused(.inSettings))
        #expect(snapshot?.pausedInSettings == true)
        let collected = try await device.gloss()
        await device.driver.syncNow()  // nothing to sync with
        #expect(device.cloud?.eventIDs.contains(collected.id) == false)

        // Paused across a launch too.
        try device.relaunch()
        await device.driver.start()
        #expect(device.engine == nil)
        await device.driver.setPaused(false)
        let second = try #require(device.engine)
        #expect(second !== first)
        #expect(second.currentState.token == first.currentState.token)  // from the saved state
        try await device.sync()
        #expect(device.cloud?.eventIDs.contains(collected.id) == true)
        #expect(await device.snapshot()?.status == .synced(atMs: device.clock.nowMs()))
    }

    @Test func overlappingStartsMakeOneEngine() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        try await device.store.set(.syncPaused, to: .bool(true))
        let driver = device.driver
        await driver.start()
        async let first: Void = driver.setPaused(false)
        async let second: Void = driver.setPaused(false)
        _ = await (first, second)
        #expect(device.icloud.engines.count == 1)
    }

    @Test func eventsOfADiscardedEngineAreIgnored() async throws {
        let device = try SyncTestDevice("phone", account: Self.account())
        await device.driver.start()
        try await device.gloss()
        let stale = FakeEngine(state: .init(), icloud: device.icloud, driver: device.driver, seed: "stale")
        await device.driver.handle(.fetchedDatabaseChanges(zoneDeletions: [.deleted]), from: stale)
        #expect(try await device.store.eventCount() == 1)
        #expect(await device.snapshot()?.notice == nil)
    }
}
