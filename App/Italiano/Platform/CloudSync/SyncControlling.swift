import Foundation
import LearningCore

/// The state of the iCloud row in Settings → Sync (docs/08 § Status UI).
enum SyncStatus: Sendable, Equatable {
    /// "Synced 2 minutes ago · iPhone, iPad, Mac".
    case synced(atMs: Int64)
    case syncing
    case waitingForNetwork
    case iCloudOff
    case paused(SyncPauseReason)
    /// No iCloud entitlement, `ITA_SYNC_ENABLED = NO` or a review build (docs/02).
    case offInThisBuild
}

/// Why sync is paused: the short reason after "Sync paused".
enum SyncPauseReason: Sendable, Equatable {
    /// `sync.paused` (Settings → Sync).
    case inSettings
    /// Another iCloud account is signed in and the learner hasn't switched to it (docs/08 § `.accountChange`).
    case otherAccount
    case storageFull
    /// CloudKit refused a record for good (logged).
    case error
}

/// What sync tells the learner once, under the iCloud row (never in an alert: docs/08 § Status UI).
enum SyncNotice: Sendable, Equatable {
    /// The `Learner` zone was deleted or purged elsewhere, and this device's progress was erased with it.
    case progressResetElsewhere
}

/// Everything Settings shows about sync.
struct SyncSnapshot: Sendable, Equatable {
    var status: SyncStatus
    /// The device families with synced progress, in display order (this device's always included).
    var platforms: [Platform]
    /// The `sync.paused` switch.
    var pausedInSettings: Bool
    /// The account-switch alert is waiting for an answer (the only sync alert there is).
    var accountSwitchPending: Bool
    var notice: SyncNotice?

    init(
        status: SyncStatus, platforms: [Platform] = [], pausedInSettings: Bool = false,
        accountSwitchPending: Bool = false, notice: SyncNotice? = nil
    ) {
        self.status = status
        self.platforms = platforms
        self.pausedInSettings = pausedInSettings
        self.accountSwitchPending = accountSwitchPending
        self.notice = notice
    }
}

/// What the App asks of sync (`AppDependencies`, docs/02): `SyncDriver` over CloudKit when the build allows it,
/// `DisabledSync` otherwise.
protocol SyncControlling: AnyObject, Sendable {
    /// The current snapshot, then every change.
    func snapshots() async -> AsyncStream<SyncSnapshot>
    /// Starts syncing at launch, after the learner store is open (docs/02 § Data flow at runtime).
    func start() async
    /// Fetches, then sends: when the app goes to the background and after a lesson step completes (docs/08).
    func syncNow() async
    /// The `sync.paused` switch (Settings → Sync).
    func setPaused(_ paused: Bool) async
    /// The account-switch alert's answer: archive this device's progress and use the new account's, or pause.
    func resolveAccountSwitch(confirm: Bool) async
    func dismissNotice() async
    /// Debug menu: delete the zone and this device's progress, then recreate the zone (docs/08 § Reset progress).
    func resetProgress() async
}

/// The status line texts (docs/08 § Status UI) and the account-switch alert.
enum SyncStatusText {
    static let title = "iCloud"
    static let syncing = "Syncing…"
    static let waitingForNetwork = "Waiting for network"
    static let iCloudOff = "iCloud is off — progress stays on this device"
    static let offInThisBuild = "Sync off in this build"
    static let pauseSwitch = "Pause sync"

    static let switchAlertTitle = "This device has progress from another iCloud account"
    static let switchAlertMessage =
        "Use the progress saved in the iCloud account you're signed in to now? This device's progress is kept as "
        + "an archive on this device. Or pause sync and keep using this device's progress."
    static let switchConfirm = "Use This Account"
    static let switchCancel = "Pause Sync"

    /// The device families in the order the status line lists them.
    static let platformOrder: [Platform] = [.iPhone, .iPad, .Mac]

    static func line(_ snapshot: SyncSnapshot, nowMs: Int64) -> String {
        switch snapshot.status {
        case .synced(let at):
            let devices = snapshot.platforms.map(\.rawValue).joined(separator: ", ")
            let synced = "Synced \(ago(at, nowMs: nowMs))"
            return devices.isEmpty ? synced : "\(synced) · \(devices)"
        case .syncing: return syncing
        case .waitingForNetwork: return waitingForNetwork
        case .iCloudOff: return iCloudOff
        case .paused(let reason): return "Sync paused · \(pauseReason(reason))"
        case .offInThisBuild: return offInThisBuild
        }
    }

    static func pauseReason(_ reason: SyncPauseReason) -> String {
        switch reason {
        case .inSettings: "Paused in Settings"
        case .otherAccount: "Another iCloud account is signed in"
        case .storageFull: "iCloud storage is full"
        case .error: "iCloud refused a change"
        }
    }

    /// "just now", "1 minute ago", "2 minutes ago", "3 hours ago", "1 day ago" (no locale: English UI, and the same
    /// on every platform).
    static func ago(_ atMs: Int64, nowMs: Int64) -> String {
        let minutes = max(0, nowMs - atMs) / 60_000
        func unit(_ n: Int64, _ name: String) -> String { n == 1 ? "1 \(name) ago" : "\(n) \(name)s ago" }
        if minutes < 1 { return "just now" }
        if minutes < 60 { return unit(minutes, "minute") }
        if minutes < 24 * 60 { return unit(minutes / 60, "hour") }
        return unit(minutes / (24 * 60), "day")
    }

    static func notice(_ notice: SyncNotice) -> String {
        switch notice {
        case .progressResetElsewhere: "Your progress was reset on another device"
        }
    }
}

/// Sync off in this build (docs/02 § Project, signing and entitlements): Settings shows "Sync off in this build"
/// and nothing syncs. Previews pass any snapshot.
final class DisabledSync: SyncControlling {
    let snapshot: SyncSnapshot

    init(snapshot: SyncSnapshot = SyncSnapshot(status: .offInThisBuild)) { self.snapshot = snapshot }

    func snapshots() async -> AsyncStream<SyncSnapshot> {
        let snapshot = snapshot
        return AsyncStream { continuation in
            continuation.yield(snapshot)
            continuation.finish()
        }
    }

    func start() async {}
    func syncNow() async {}
    func setPaused(_ paused: Bool) async {}
    func resolveAccountSwitch(confirm: Bool) async {}
    func dismissNotice() async {}
    func resetProgress() async {}
}
