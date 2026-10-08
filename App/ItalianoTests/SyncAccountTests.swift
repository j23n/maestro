import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// docs/08 § `.accountChange` (task M7.4's proxy): sign-in, sign-out and account switches through fake account
/// events, including the archive and the fresh database after the learner confirms a switch.
@Suite struct SyncAccountTests {
    let alice = FakeCloud()
    let bob = FakeCloud()

    func aliceAccount() -> FakeICloud.Account { .init(user: "_alice", cloud: alice) }
    func bobAccount() -> FakeICloud.Account { .init(user: "_bob", cloud: bob) }

    func archives(in folder: URL) throws -> [String] {
        try FileManager.default.contentsOfDirectory(atPath: folder.path).filter { $0.hasSuffix(".archive.sqlite") }
    }

    @Test func signingInWithNoPreviousAccountUploadsWhatWasDoneOnThisDevice() async throws {
        let device = try SyncTestDevice("phone", account: nil)
        await device.driver.start()
        #expect(await device.snapshot()?.status == .iCloudOff)
        let offline = try await device.lesson(outcomes: [.correct, .wrong])
        try await device.set(.goalDaysPerWeek, .number(3))
        try await device.sync()  // no account: nothing happens
        #expect(try await device.store.syncAccount() == nil)

        device.icloud.account = aliceAccount()
        try await device.sync()  // the engine announces the sign-in; everything local goes up
        #expect(try await device.store.syncAccount() == "_alice")
        #expect(alice.recordNames == Set(offline.map(\.id) + ["setting.goal.daysPerWeek"]))
        #expect(try await device.pendingNames.isEmpty)
        #expect(await device.snapshot()?.status == .synced(atMs: device.clock.nowMs()))
    }

    @Test func signingOutKeepsEverythingLocal() async throws {
        let device = try SyncTestDevice("phone", account: aliceAccount())
        await device.driver.start()
        let log = try await device.lesson(outcomes: [.correct])
        try await device.sync()
        let engine = try #require(device.engine)
        device.icloud.account = nil
        await engine.emit(.accountChange(.signOut(previousUser: "_alice")))
        #expect(await device.snapshot()?.status == .iCloudOff)
        let later = try await device.gloss()
        try await device.sync()
        #expect(try await device.store.eventCount() == log.count + 1)
        #expect(try await device.pendingNames == [later.id])
        #expect(try await device.store.syncAccount() == "_alice")

        // Signing in again to the same account carries on (and uploads what collected).
        device.icloud.account = aliceAccount()
        await engine.emit(.accountChange(.signIn(currentUser: "_alice")))
        try await device.sync()
        #expect(alice.eventIDs.contains(later.id))
        #expect(await device.snapshot()?.accountSwitchPending == false)
    }

    @Test func aSignInToAnotherAccountAfterASignOutIsASwitch() async throws {
        let device = try SyncTestDevice("phone", account: aliceAccount())
        await device.driver.start()
        try await device.lesson(outcomes: [.correct])
        try await device.sync()
        let engine = try #require(device.engine)
        device.icloud.account = nil
        await engine.emit(.accountChange(.signOut(previousUser: "_alice")))
        let offline = try await device.gloss()
        device.icloud.account = bobAccount()
        await engine.emit(.accountChange(.signIn(currentUser: "_bob")))

        let snapshot = await device.snapshot()
        #expect(snapshot?.accountSwitchPending == true)
        #expect(snapshot?.status == .paused(.otherAccount))
        #expect(await eventually { engine.isDiscarded })
        try await device.sync()  // nothing reaches Bob's database while the alert is up
        #expect(bob.recordNames.isEmpty)
        #expect(try await device.pendingNames == [offline.id])
    }

    @Test func confirmingASwitchArchivesThisDeviceAndStartsFromTheNewAccount() async throws {
        // Bob already has progress from his own iPad.
        let pad = try SyncTestDevice("pad", platform: .iPad, account: bobAccount())
        await pad.driver.start()
        let bobsLog = try await pad.lesson(outcomes: [.correct, .correct])
        try await pad.sync()

        let device = try SyncTestDevice("phone", account: aliceAccount())
        await device.driver.start()
        let alicesLog = try await device.lesson(outcomes: [.wrong])
        try await device.set(.profileName, .string("Alice"))
        try await device.set(.displayTextScale, .number(1.3))
        try await device.sync()
        let oldDevice = device.store.deviceId

        device.icloud.account = bobAccount()
        try await device.sync()  // the engine sees another account than the one it last synced with
        #expect(await device.snapshot()?.accountSwitchPending == true)
        #expect(device.box.replacements == 0)

        await device.driver.resolveAccountSwitch(confirm: true)
        #expect(device.box.replacements == 1)
        #expect(try archives(in: device.folder).count == 1)
        #expect(device.store.deviceId != oldDevice)
        #expect(try await device.store.syncAccount() == "_bob")
        #expect(device.store.settings.textScale == 1.0)  // a fresh database
        try await device.sync()
        #expect(Set(try await device.store.events().map(\.id)) == Set(bobsLog.map(\.id)))
        #expect(device.store.state == pad.store.state)
        #expect(bob.eventIDs.isDisjoint(with: alicesLog.map(\.id)))
        #expect(alice.eventIDs == Set(alicesLog.map(\.id)))
        let snapshot = await device.snapshot()
        #expect(snapshot?.accountSwitchPending == false)
        #expect(snapshot?.status == .synced(atMs: device.clock.nowMs()))
        #expect(snapshot?.platforms == [.iPhone, .iPad])

        // The archive is Alice's database, intact.
        let archive = device.folder.appendingPathComponent(try #require(try archives(in: device.folder).first))
        let archived = try LearnerStore(
            url: archive, content: SyncTestCourse.content, clock: device.clock, ids: SeededUUIDSource(seed: "x"))
        defer { try? archived.close() }
        #expect(Set(try await archived.events().map(\.id)) == Set(alicesLog.map(\.id)))
        #expect(archived.settings.profileName == "Alice")
    }

    @Test func cancellingASwitchPausesSyncAndKeepsThisDevicesProgress() async throws {
        let device = try SyncTestDevice("phone", account: aliceAccount())
        await device.driver.start()
        let log = try await device.lesson(outcomes: [.correct])
        try await device.sync()
        device.icloud.account = bobAccount()
        try await device.sync()
        await device.driver.resolveAccountSwitch(confirm: false)

        var snapshot = await device.snapshot()
        #expect(snapshot?.accountSwitchPending == false)
        #expect(snapshot?.status == .paused(.otherAccount))
        #expect(snapshot?.pausedInSettings == true)
        #expect(device.store.settings.syncPaused)
        #expect(device.box.replacements == 0)
        #expect(try await device.store.eventCount() == log.count)
        try await device.gloss()
        try await device.sync()
        #expect(bob.recordNames.isEmpty)

        // After a relaunch it is simply paused; unpausing asks again.
        try device.relaunch()
        await device.driver.start()
        #expect(await device.snapshot()?.status == .paused(.inSettings))
        await device.driver.setPaused(false)
        snapshot = await device.snapshot()
        #expect(snapshot?.accountSwitchPending == true)
        #expect(device.engine == nil)
    }

    @Test func confirmingAfterTheAccountChangedBackArchivesNothing() async throws {
        let device = try SyncTestDevice("phone", account: aliceAccount())
        await device.driver.start()
        try await device.gloss()
        try await device.sync()
        device.icloud.account = bobAccount()
        try await device.sync()
        #expect(await device.snapshot()?.accountSwitchPending == true)
        device.icloud.account = aliceAccount()  // back before the learner answered
        await device.driver.resolveAccountSwitch(confirm: true)
        #expect(try archives(in: device.folder).isEmpty)
        #expect(device.box.replacements == 0)
        #expect(device.engine != nil)
        let later = try await device.gloss()
        try await device.sync()
        #expect(alice.eventIDs.contains(later.id))
        #expect(bob.recordNames.isEmpty)
        #expect(await device.snapshot()?.status == .synced(atMs: device.clock.nowMs()))
    }

    @Test func launchingWithAnotherAccountSignedInAsksBeforeAnEngineStarts() async throws {
        let device = try SyncTestDevice("phone", account: aliceAccount())
        await device.driver.start()
        try await device.gloss()
        try await device.sync()
        device.icloud.account = bobAccount()
        try device.relaunch()
        let enginesBefore = device.icloud.engines.count
        await device.driver.start()
        #expect(device.icloud.engines.count == enginesBefore)
        #expect(await device.snapshot()?.accountSwitchPending == true)
        #expect(bob.recordNames.isEmpty)
    }
}
