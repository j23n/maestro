import SwiftUI

/// Settings → Sync (`Settings.png`, docs/08 § Status UI): the iCloud row ("Synced 2 minutes ago · iPhone, iPad,
/// Mac"), the one-time notice under it, and "Pause sync". Task M3.8 puts it first on the Settings screen; the
/// account-switch alert goes on the root view with `syncAccountSwitchAlert(_:)`.
struct SyncSettingsSection: View {
    let model: SyncSettingsModel

    var body: some View {
        SettingsGroup("Sync") {
            SyncStatusRow(model: model)
            if model.showsPauseSwitch {
                Toggle(
                    isOn: Binding(
                        get: { model.isPaused },
                        set: { paused in Task { await model.setPaused(paused) } })
                ) {
                    Text(SyncStatusText.pauseSwitch).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                }
                .toggleStyle(DSToggleStyle())
                .accessibilityLabel(SyncStatusText.pauseSwitch)
                .accessibilityIdentifier("settings.sync.pause")
            }
        }
        .task { await model.observe() }
    }
}

/// The iCloud row: an icon, "iCloud", and the status line, refreshed every minute so "2 minutes ago" stays true.
struct SyncStatusRow: View {
    let model: SyncSettingsModel

    var body: some View {
        TimelineView(.everyMinute) { context in
            HStack(alignment: .top, spacing: Tokens.Space.l) {
                Image(systemName: model.icon.systemName)
                    .foregroundStyle(model.icon == .synced ? Color.ds.success : Color.ds.secondary)
                    .dsFont(Tokens.TypeScale.rowTitle)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: Tokens.Space.xxs) {
                    Text(model.title).dsFont(Tokens.TypeScale.rowTitle).foregroundStyle(Color.ds.ink)
                    Text(model.statusLine(nowMs: Int64(context.date.timeIntervalSince1970 * 1000)))
                        .dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                        .accessibilityIdentifier("settings.sync.status")
                    if let notice = model.noticeText {
                        HStack(alignment: .firstTextBaseline, spacing: Tokens.Space.s) {
                            Text(notice).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.warningText)
                            Spacer(minLength: Tokens.Space.s)
                            Button("OK") { Task { await model.dismissNotice() } }
                                .dsFont(Tokens.TypeScale.uiButton).foregroundStyle(Color.ds.accent)
                                .frame(minWidth: Tokens.Size.minTouch, minHeight: Tokens.Size.minTouch)
                                .accessibilityLabel("Dismiss")
                                .accessibilityIdentifier("settings.sync.notice.dismiss")
                        }
                        .padding(.top, Tokens.Space.xs)
                    }
                }
            }
            .padding(.vertical, Tokens.Space.m)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("settings.sync.row")
        }
    }
}

extension SyncStatusIcon {
    var systemName: String {
        switch self {
        case .synced: "checkmark.icloud"
        case .syncing: "arrow.triangle.2.circlepath.icloud"
        case .waiting: "wifi.slash"
        case .off: "icloud.slash"
        case .paused: "pause.circle"
        }
    }
}

extension View {
    /// "This device has progress from another iCloud account" (docs/08 § `.accountChange`): the only sync alert.
    /// Use This Account archives this device's progress and downloads the account's; Pause Sync keeps it.
    func syncAccountSwitchAlert(_ model: SyncSettingsModel) -> some View {
        alert(
            SyncStatusText.switchAlertTitle,
            isPresented: Binding(get: { model.isAccountSwitchAlertPresented }, set: { _ in })
        ) {
            Button(SyncStatusText.switchConfirm) { Task { await model.resolveAccountSwitch(confirm: true) } }
                .accessibilityIdentifier("sync.switchAlert.confirm")
            Button(SyncStatusText.switchCancel, role: .cancel) {
                Task { await model.resolveAccountSwitch(confirm: false) }
            }
            .accessibilityIdentifier("sync.switchAlert.pause")
        } message: {
            Text(SyncStatusText.switchAlertMessage)
        }
    }
}

#Preview("Synced") {
    let snapshot = SyncSnapshot(
        status: .synced(atMs: Int64(Date().timeIntervalSince1970 * 1000) - 120_000), platforms: [.iPhone, .iPad, .Mac])
    SyncSettingsSection(model: SyncSettingsModel(sync: DisabledSync(snapshot: snapshot), snapshot: snapshot))
        .padding()
        .background(Color.ds.background)
}
