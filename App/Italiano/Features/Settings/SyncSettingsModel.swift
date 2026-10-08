import Foundation
import LearningCore
import Observation

/// The icon of the iCloud row (the view maps it to a symbol).
enum SyncStatusIcon: Sendable, Equatable {
    case synced, syncing, waiting, off, paused
}

/// Settings → Sync (`Settings.png`, docs/08 § Status UI): the iCloud row, the "Pause sync" switch, the one-time
/// notice, and the account-switch alert (presented from the root view: it's the only sync alert there is).
@MainActor
@Observable
final class SyncSettingsModel {
    private(set) var snapshot: SyncSnapshot
    private let sync: any SyncControlling
    /// The learner answered the alert; it stays down until the answer lands.
    private var answeredSwitch = false

    init(sync: any SyncControlling, snapshot: SyncSnapshot = SyncSnapshot(status: .syncing)) {
        self.sync = sync
        self.snapshot = snapshot
    }

    /// Follows the controller until the calling task is cancelled (the view's `.task`).
    func observe() async {
        for await next in await sync.snapshots() { apply(next) }
    }

    func apply(_ next: SyncSnapshot) {
        snapshot = next
        if !next.accountSwitchPending { answeredSwitch = false }
    }

    var title: String { SyncStatusText.title }

    /// The row's second line; the view refreshes it every minute ("Synced 2 minutes ago · iPhone, iPad, Mac").
    func statusLine(nowMs: Int64) -> String { SyncStatusText.line(snapshot, nowMs: nowMs) }

    var icon: SyncStatusIcon {
        switch snapshot.status {
        case .synced: .synced
        case .syncing: .syncing
        case .waitingForNetwork: .waiting
        case .iCloudOff, .offInThisBuild: .off
        case .paused: .paused
        }
    }

    /// No switch in a build without sync.
    var showsPauseSwitch: Bool { snapshot.status != .offInThisBuild }
    var isPaused: Bool { snapshot.pausedInSettings }

    func setPaused(_ paused: Bool) async {
        snapshot.pausedInSettings = paused  // the switch follows the finger; the driver's snapshot confirms it
        await sync.setPaused(paused)
    }

    var noticeText: String? { snapshot.notice.map(SyncStatusText.notice) }

    func dismissNotice() async {
        snapshot.notice = nil
        await sync.dismissNotice()
    }

    var isAccountSwitchAlertPresented: Bool { snapshot.accountSwitchPending && !answeredSwitch }

    func resolveAccountSwitch(confirm: Bool) async {
        answeredSwitch = true
        await sync.resolveAccountSwitch(confirm: confirm)
    }
}
