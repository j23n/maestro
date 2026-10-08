import Foundation
import GRDB
import LearningCore
import LearningCoreTestSupport
import Testing

@testable import Storage

/// What the sync driver (task M7.2–M7.4) needs beyond the M2.12 bookkeeping: the pending-additions stream, the
/// bound iCloud account, forgetting every system field, and the platforms of the devices seen (docs/08).
@Suite struct LearnerSyncTests {
    func factory(_ db: TestLearnerDB, device: String = "dev") -> EventFactory {
        EventFactory(deviceId: device, packVersion: "0.1.0", clock: db.clock, ids: SeededUUIDSource(seed: device))
    }

    func gloss(_ factory: EventFactory) -> Event {
        factory.glossTapped(textId: TextID("u00.l1.story"), line: 1, token: 1, itemId: nil)
    }

    @Test func pendingAdditionsYieldWhatLocalWritesMarkedPending() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        let local = factory(db)
        var additions = store.pendingAdditions().makeAsyncIterator()

        let first = [gloss(local), gloss(local)]
        try await store.append(first)
        #expect(await additions.next() == first.map(\.id))

        // None of these yields: a duplicate append, a remote insert, a device setting and the driver's own writes.
        try await store.append(first[0])
        try await store.insertRemote([gloss(factory(db, device: "pad"))])
        try await store.set(.displayTextScale, to: .number(1.2))
        try await store.addPending(recordNames: ["setting.profile.name"])
        try await store.markEverythingPending()
        // A synced setting yields every time it changes, even when it is already pending.
        try await store.set(.goalDaysPerWeek, to: .number(3))
        #expect(await additions.next() == ["setting.goal.daysPerWeek"])
        try await store.set(.goalDaysPerWeek, to: .number(4))
        #expect(await additions.next() == ["setting.goal.daysPerWeek"])

        let queued = gloss(local)
        store.enqueueAppend(queued)
        #expect(await additions.next() == [queued.id])

        try store.close()
        #expect(await additions.next() == nil)
    }

    /// `close()` used to finish the streams while holding the lock their `onTermination` takes (a deadlock).
    @Test func closingEndsEveryOpenStream() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        var states = store.states().makeAsyncIterator()
        var settings = store.settingsUpdates().makeAsyncIterator()
        var additions = store.pendingAdditions().makeAsyncIterator()
        #expect(await states.next() != nil)
        #expect(await settings.next() != nil)
        try store.close()
        #expect(await states.next() == nil)
        #expect(await settings.next() == nil)
        #expect(await additions.next() == nil)
    }

    @Test func aRolledBackAppendYieldsNothing() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let local = factory(db)
        var additions = store.pendingAdditions().makeAsyncIterator()
        try await store.pool.write { db in
            try db.execute(
                sql: "CREATE TRIGGER injected BEFORE INSERT ON sync_pending BEGIN SELECT RAISE(ABORT, 'x'); END")
        }
        await #expect(throws: StorageError.self) { try await store.append(gloss(local)) }
        try await store.pool.write { db in try db.execute(sql: "DROP TRIGGER injected") }
        let next = gloss(local)
        try await store.append(next)
        #expect(await additions.next() == [next.id])
    }

    @Test func theSyncAccountIsKeptAcrossEraseAndReopen() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        #expect(try await store.syncAccount() == nil)
        try await store.setSyncAccount("_user-a")
        try await store.setSyncAccount("_user-b")
        try await store.eraseProgress()
        #expect(try await store.syncAccount() == "_user-b")
        try store.close()
        let reopened = try db.open()
        defer { try? reopened.close() }
        #expect(try await reopened.syncAccount() == "_user-b")
        try await reopened.setSyncAccount(nil)
        #expect(try await reopened.syncAccount() == nil)
        #expect(reopened.deviceId == store.deviceId)
    }

    @Test func everySystemFieldCanBeForgotten() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        try await store.saveSystemFields(Data([1]), recordName: "setting.profile.name")
        try await store.saveSystemFields(Data([2]), recordName: "setting.goal.daysPerWeek")
        try await store.removeAllSystemFields()
        #expect(try count(store, "cloud_system_fields") == 0)
    }

    @Test func devicePlatformsComeFromEachDevicesLatestSessionEvent() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        #expect(try await store.devicePlatforms().isEmpty)
        let phone = factory(db, device: store.deviceId)
        let pad = factory(db, device: "pad")
        let mac = factory(db, device: "mac")
        func session(_ f: EventFactory, _ platform: Platform) -> Event {
            db.clock.advance(byMs: 1_000)
            return f.session(
                sessionId: "s", kind: .lesson, platform: platform, startedAt: db.clock.nowMs(),
                endedAt: db.clock.nowMs(), activeSeconds: 1)
        }
        try await store.append([session(phone, .iPhone), gloss(phone)])
        // A device's latest session wins (a restored backup on another device family keeps its device ID).
        try await store.insertRemote([session(pad, .Mac), session(pad, .iPad), gloss(mac)])
        // A newer client's platform and a payload that isn't JSON are left out, not fatal.
        let future = SyncRecord(
            recordType: .event, recordName: "0f0e0000-0000-4000-8000-000000000001",
            fields: [
                "type": .string("session"), "at": .int64(db.clock.nowMs()), "tzOffsetMin": .int64(0),
                "deviceId": .string("vision"), "schema": .int64(1), "packVersion": .string("0.1.0"),
                "payload": .bytes(Data(#"{"platform":"Vision","sessionId":"s"}"#.utf8)),
            ])
        var broken = future
        broken.recordName = "0f0e0000-0000-4000-8000-000000000002"
        broken.fields["deviceId"] = .string("broken")
        broken.fields["payload"] = .bytes(Data("not json".utf8))
        try await store.insertRemote(records: [future, broken])
        #expect(try count(store, "events") == 7)

        #expect(try await store.devicePlatforms() == [store.deviceId: .iPhone, "pad": .iPad])
    }
}
