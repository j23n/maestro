import SwiftUI

/// The app's entry point: one window with the tab shell on every platform, the Settings scene on macOS
/// (docs/07 § Navigation). Fonts are registered before the first view draws.
@main
struct ItalianoApp: App {
    @State private var deps: AppDependencies

    init() {
        FontRegistry.registerBundledFonts()
        _deps = State(initialValue: AppDependencies.live())
    }

    var body: some Scene {
        WindowGroup {
            RootView(deps: deps)
                .modifier(CompactWidthReader())
        }
        #if os(macOS)
            .defaultSize(width: Tokens.Size.macMinWindowWidth + 200, height: Tokens.Size.macMinWindowHeight + 180)
        #endif
        #if os(macOS)
            Settings {
                SettingsScreen(app: deps.app, sync: deps.syncSettings, studyBuild: deps.config.studyBuild)
                    .frame(minWidth: 520, minHeight: 480)
            }
        #endif
    }
}

/// Loading, the two launch errors (docs/02 § Logging and errors), then the tabs.
struct RootView: View {
    let deps: AppDependencies
    @State private var showRecovery = false
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
            switch deps.app.phase {
            case .loading:
                VStack(spacing: Tokens.Space.l) {
                    Mascot(pose: .sleep, size: 96, decorative: true)
                    ProgressView().accessibilityIdentifier("launch.progress")
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color.ds.background)
            case .packMismatch:
                LaunchErrorView(
                    title: "This version needs an update",
                    message: "The course content doesn't match this version of Italiano. Update the app to keep going; "
                        + "your progress is safe.",
                    identifier: "error.packMismatch")
            case .failed(let detail):
                LaunchErrorView(
                    title: "Italiano couldn't start",
                    message: "Something went wrong opening the course. Quit and open Italiano again.",
                    detail: deps.config.debugMenu ? detail : nil, identifier: "error.launch")
            case .ready:
                if deps.app.isOnboarded && deps.app.placementPending {
                    PlacementHost(deps: deps)
                } else if deps.app.isOnboarded {
                    MainTabs(deps: deps)
                } else {
                    OnboardingView(
                        app: deps.app, studyBuild: deps.config.studyBuild, syncAllowed: deps.config.syncAllowed)
                }
            }
        }
        .task {
            await deps.app.start()
            if deps.app.phase == .ready { await deps.startSync() }
        }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .background else { return }
            Task {
                await deps.app.settle()
                try? await deps.app.store?.checkpoint()
                await deps.app.sync?.syncNow()
            }
        }
        .modifier(SyncAlertModifier(model: deps.syncSettings))
        .onChange(of: deps.app.recoveryNotice) { _, notice in showRecovery = notice != nil }
        .alert("Your progress was reset on this device", isPresented: $showRecovery) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(deps.app.recoveryNotice ?? "")
        }
    }
}

struct LaunchErrorView: View {
    let title: String
    let message: String
    var detail: String?
    let identifier: String

    var body: some View {
        VStack(spacing: Tokens.Space.xxl) {
            Mascot(pose: .think, size: 120, decorative: true)
            Text(title).dsFont(Tokens.TypeScale.screenTitle).foregroundStyle(Color.ds.ink)
                .multilineTextAlignment(.center)
            Text(message).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
                .multilineTextAlignment(.center)
            if let detail {
                Text(detail).font(.footnote.monospaced()).foregroundStyle(Color.ds.secondary).textSelection(.enabled)
            }
        }
        .readableColumn()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.ds.background)
        .accessibilityIdentifier(identifier)
    }
}

/// The account-switch alert once sync has started (docs/08 § `.accountChange`).
private struct SyncAlertModifier: ViewModifier {
    let model: SyncSettingsModel?

    func body(content: Content) -> some View {
        if let model { content.syncAccountSwitchAlert(model) } else { content }
    }
}
