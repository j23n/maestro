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
    /// Whether speaking exercises appear, and the Italian model's download (docs/09); nil without a recogniser.
    let speech: SpeechSettingsModel?

    init(
        config: AppConfig, app: AppModel, notifications: any NotificationScheduling, telemetry: StudyTelemetry?,
        debug: DebugMenuModel?, speech: (any SpeechRecognizing)? = nil
    ) {
        self.config = config
        self.app = app
        reminders = ReminderSettingsModel(app: app, scheduler: notifications)
        textSize = TextSizeController(app: app)
        self.telemetry = telemetry
        self.debug = config.debugMenu ? debug : nil
        self.speech = speech.map { SpeechSettingsModel(app: app, speech: $0) }
    }

    /// After `AppModel.start()` and sync: speech availability, the Debug menu's data and launch arguments, the
    /// stored reminder, and the first upload with periodic uploads after it. Nothing happens when the app couldn't
    /// start.
    func afterLaunch(arguments: [String]) async {
        guard app.phase == .ready else { return }
        app.onSessionEnded = { [weak self] in self?.sessionEnded() }
        await speech?.refresh()
        if let debug {
            await debug.load()
            let launch = LaunchArguments(arguments)
            if launch.autoAnswer { debug.enableAutoAnswerForThisLaunch() }
            if let unit = launch.jumpToUnit { await debug.jumpAtLaunch(to: unit) }
        }
        await reminders.refresh()
        if let telemetry {
            telemetry.startPeriodicUploads()
            await telemetry.uploadNow()
        }
    }

    /// Uploads run every 15 minutes while active and once more when the app goes to the background (docs/12).
    /// Becoming active also asks the recogniser again: microphone access may have changed in system settings.
    func activityChanged(_ activity: AppActivity) {
        guard app.phase == .ready else { return }
        switch activity {
        case .active:
            if let speech { Task { await speech.refresh() } }
            app.deleteExpiredFinalChecks()  // the 30 days also run out while the app stays open (docs/09)
            telemetry?.startPeriodicUploads()
        case .background:
            guard let telemetry else { return }
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
