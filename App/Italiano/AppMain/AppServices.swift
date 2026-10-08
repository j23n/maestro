import Foundation
import LearningCore

/// The scene's activity, as RootView reports it (SwiftUI's `ScenePhase`, without importing SwiftUI here).
enum AppActivity: Sendable, Equatable {
    case active, inactive, background
}

/// The app shell's services around `AppModel` (tasks M3.3, M3.10, M6.5): daily reminders, study telemetry and the
/// Debug menu, and what each does at launch, when the scene changes and when a session ends. Platform-neutral so
/// the wiring is tested on Linux; `AppDependencies` creates it and RootView calls it.
@MainActor
final class AppServices {
    let config: AppConfig
    let app: AppModel
    let reminders: ReminderSettingsModel
    /// View → Bigger Text, Smaller Text, Actual Size (the Mac menus).
    let textSize: TextSizeController
    /// Study builds that can upload (`AppConfig.canUploadTelemetry`); nil otherwise.
    let telemetry: StudyTelemetry?
    /// Builds with `ITA_DEBUG_MENU`; nil otherwise, so Release and Study builds have no Debug menu.
    let debug: DebugMenuModel?

    init(
        config: AppConfig, app: AppModel, notifications: any NotificationScheduling, telemetry: StudyTelemetry?,
        debug: DebugMenuModel?
    ) {
        self.config = config
        self.app = app
        reminders = ReminderSettingsModel(app: app, scheduler: notifications)
        textSize = TextSizeController(app: app)
        self.telemetry = telemetry
        self.debug = config.debugMenu ? debug : nil
    }

    /// After `AppModel.start()` and sync: the Debug menu's data and the launch argument, the stored reminder, and
    /// the first upload with periodic uploads after it. Nothing happens when the app couldn't start.
    func afterLaunch(arguments: [String]) async {
        guard app.phase == .ready else { return }
        app.onSessionEnded = { [weak self] in self?.sessionEnded() }
        if let debug {
            await debug.load()
            if let unit = LaunchArguments(arguments).jumpToUnit { await debug.jumpAtLaunch(to: unit) }
        }
        await reminders.refresh()
        if let telemetry {
            telemetry.startPeriodicUploads()
            await telemetry.uploadNow()
        }
    }

    /// Uploads run every 15 minutes while active and once more when the app goes to the background (docs/12).
    func activityChanged(_ activity: AppActivity) {
        guard let telemetry, app.phase == .ready else { return }
        switch activity {
        case .active:
            telemetry.startPeriodicUploads()
        case .background:
            telemetry.stopPeriodicUploads()
            Task { await telemetry.uploadNow() }
        case .inactive:
            break
        }
    }

    private func sessionEnded() {
        guard let telemetry else { return }
        Task { await telemetry.uploadNow() }
    }
}
