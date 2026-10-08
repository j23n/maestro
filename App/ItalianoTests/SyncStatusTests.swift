import Foundation
import LearningCore
import Testing

@testable import Italiano

/// docs/08 § Status UI (task M7.3): the iCloud row's texts, the Settings sync model and the build switch.
@MainActor
@Suite struct SyncStatusTests {
    let now: Int64 = 1_767_603_600_000

    func line(_ status: SyncStatus, platforms: [Platform] = []) -> String {
        SyncStatusText.line(SyncSnapshot(status: status, platforms: platforms), nowMs: now)
    }

    @Test func everyStatusReadsAsDocs08Says() {
        #expect(
            line(.synced(atMs: now - 2 * 60_000), platforms: [.iPhone, .iPad, .Mac])
                == "Synced 2 minutes ago · iPhone, iPad, Mac")
        #expect(line(.syncing) == "Syncing…")
        #expect(line(.waitingForNetwork) == "Waiting for network")
        #expect(line(.iCloudOff) == "iCloud is off — progress stays on this device")
        #expect(line(.paused(.inSettings)) == "Sync paused · Paused in Settings")
        #expect(line(.paused(.storageFull)) == "Sync paused · iCloud storage is full")
        #expect(line(.paused(.otherAccount)) == "Sync paused · Another iCloud account is signed in")
        #expect(line(.paused(.error)) == "Sync paused · iCloud refused a change")
        #expect(line(.offInThisBuild) == "Sync off in this build")
        #expect(line(.synced(atMs: now), platforms: []) == "Synced just now")
        #expect(SyncStatusText.title == "iCloud")
        #expect(SyncStatusText.switchAlertTitle == "This device has progress from another iCloud account")
        #expect(SyncStatusText.notice(.progressResetElsewhere) == "Your progress was reset on another device")
    }

    @Test(
        arguments: [
            (0, "just now"), (59_999, "just now"), (60_000, "1 minute ago"), (2 * 60_000, "2 minutes ago"),
            (59 * 60_000, "59 minutes ago"), (60 * 60_000, "1 hour ago"),
            (23 * 3_600_000 + 59 * 60_000, "23 hours ago"),
            (24 * 3_600_000, "1 day ago"), (3 * 86_400_000, "3 days ago"), (-5_000, "just now"),
        ] as [(Int64, String)])
    func relativeTimes(elapsed: Int64, text: String) {
        #expect(SyncStatusText.ago(now - elapsed, nowMs: now) == text)
    }

    @Test func aBuildWithoutSyncShowsItAndNoSwitch() async {
        let model = SyncSettingsModel(sync: DisabledSync())
        await model.observe()
        #expect(model.statusLine(nowMs: now) == "Sync off in this build")
        #expect(model.icon == .off)
        #expect(!model.showsPauseSwitch)
        #expect(!model.isAccountSwitchAlertPresented)
    }

    @Test func syncRunsOnlyWithTheSwitchAndTheEntitlement() {
        let signed = ["ITA_SYNC_ENABLED": "YES", "ITA_ICLOUD_ENTITLEMENT": "YES"]
        #expect(AppConfig(info: signed).syncAllowed)
        #expect(!AppConfig(info: ["ITA_SYNC_ENABLED": "YES"]).syncAllowed)
        #expect(!AppConfig(info: ["ITA_ICLOUD_ENTITLEMENT": "YES"]).syncAllowed)
        #expect(!AppConfig(info: signed.merging(["ITA_REVIEW_MODE": "YES"]) { $1 }).syncAllowed)
        #expect(
            !AppConfig(info: ["ITA_SYNC_ENABLED": "YES", "ITA_ICLOUD_ENTITLEMENT": "$(ITA_ICLOUD_ENTITLEMENT)"])
                .syncAllowed)
    }

    @Test func theModelFollowsTheDriverAndAnswersTheAlertOnce() async {
        let sync = ScriptedSync()
        let model = SyncSettingsModel(sync: sync)
        model.apply(SyncSnapshot(status: .synced(atMs: now - 60_000), platforms: [.iPhone, .Mac]))
        #expect(model.statusLine(nowMs: now) == "Synced 1 minute ago · iPhone, Mac")
        #expect(model.icon == .synced)
        #expect(model.showsPauseSwitch)

        model.apply(SyncSnapshot(status: .paused(.otherAccount), accountSwitchPending: true))
        #expect(model.isAccountSwitchAlertPresented)
        #expect(model.icon == .paused)
        await model.resolveAccountSwitch(confirm: true)
        #expect(await sync.calls == ["resolve true"])
        #expect(!model.isAccountSwitchAlertPresented)  // down at once, before the driver's answer lands
        model.apply(SyncSnapshot(status: .paused(.otherAccount), accountSwitchPending: true))
        #expect(!model.isAccountSwitchAlertPresented)  // a late copy of the old snapshot doesn't bring it back
        model.apply(SyncSnapshot(status: .syncing))
        model.apply(SyncSnapshot(status: .paused(.otherAccount), accountSwitchPending: true))
        #expect(model.isAccountSwitchAlertPresented)  // a new switch asks again

        await model.setPaused(true)
        #expect(model.isPaused)
        model.apply(SyncSnapshot(status: .syncing, notice: .progressResetElsewhere))
        #expect(model.noticeText == "Your progress was reset on another device")
        await model.dismissNotice()
        #expect(model.noticeText == nil)
        #expect(await sync.calls == ["resolve true", "pause true", "dismiss"])
    }

    @Test func theModelObservesTheRealDriver() async throws {
        let device = try SyncTestDevice("phone", platform: .Mac, account: .init(user: "_a", cloud: FakeCloud()))
        let model = SyncSettingsModel(sync: device.driver)
        let observing = Task { await model.observe() }
        defer { observing.cancel() }
        await device.driver.start()
        try await device.sync()
        #expect(await eventuallyOnMain { model.snapshot.status == .synced(atMs: device.clock.nowMs()) })
        #expect(model.statusLine(nowMs: device.clock.nowMs() + 120_000) == "Synced 2 minutes ago · Mac")
        await model.setPaused(true)
        #expect(await eventuallyOnMain { model.snapshot.status == .paused(.inSettings) })
        #expect(model.statusLine(nowMs: 0) == "Sync paused · Paused in Settings")
    }
}

/// A `SyncControlling` that records what the model asks.
actor ScriptedSync: SyncControlling {
    private(set) var calls: [String] = []

    func snapshots() -> AsyncStream<SyncSnapshot> { AsyncStream { $0.finish() } }
    func start() {}
    func syncNow() {}
    func setPaused(_ paused: Bool) { calls.append("pause \(paused)") }
    func resolveAccountSwitch(confirm: Bool) { calls.append("resolve \(confirm)") }
    func dismissNotice() { calls.append("dismiss") }
    func resetProgress() { calls.append("reset") }
}
