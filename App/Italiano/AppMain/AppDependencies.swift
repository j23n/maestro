import LearningCore
import SwiftUI

#if canImport(UIKit)
    import UIKit
#endif

/// The app's dependency container (docs/02 § App): build configuration, the runtime model, and the platform
/// adapters behind their protocols. Previews and UI tests swap in fakes with `AppDependencies.preview`.
@MainActor
final class AppDependencies {
    let config: AppConfig
    let app: AppModel
    let audioPlayer: any AudioPlaying
    let speech: any SpeechRecognizing
    let notifications: any NotificationScheduling
    /// Reminders, study telemetry, text size and the Debug menu (platform-neutral, `AppServices`).
    let services: AppServices
    /// The content lead's review mode (M6.10): only in builds with `ITA_REVIEW_MODE = YES`, and active only on a
    /// dev pack; nil for learners.
    let review: ReviewMode?
    /// Settings → Sync and the account-switch alert; set once sync starts.
    private(set) var syncSettings: SyncSettingsModel?

    init(
        config: AppConfig, app: AppModel, audioPlayer: any AudioPlaying, speech: any SpeechRecognizing,
        notifications: any NotificationScheduling, telemetry: StudyTelemetry? = nil, debug: DebugMenuModel? = nil,
        review: ReviewMode? = nil
    ) {
        self.config = config
        self.app = app
        self.audioPlayer = audioPlayer
        self.speech = speech
        self.notifications = notifications
        services = AppServices(
            config: config, app: app, notifications: notifications, telemetry: telemetry, debug: debug)
        self.review = review
    }

    /// The real app: the bundled pack (`Resources/Content/content.sqlite`), the learner database in Application
    /// Support, AVFoundation playback, SpeechAnalyzer and UserNotifications.
    /// Builds with the Debug menu run on `DebugClock` (the clock offset) and wrap the recogniser for "Simulate
    /// speech by typing"; study builds that can upload get the telemetry uploader (docs/12).
    static func live() -> AppDependencies {
        let config = AppConfig.fromMainBundle()
        let packURL =
            Bundle.main.url(forResource: "content", withExtension: "sqlite", subdirectory: "Content")
            ?? Bundle.main.bundleURL.appendingPathComponent("Content/content.sqlite")
        let preferences = UserDefaults.standard
        let debugClock =
            config.debugMenu
            ? DebugClock(base: SystemClock(), offsetDays: DebugMenuModel.storedClockOffset(preferences)) : nil
        let app = AppModel(
            env: .init(
                packURL: packURL, learnerURL: nil, clock: debugClock ?? SystemClock(), ids: SystemUUIDSource(),
                platform: DevicePlatform.current))
        let recognizer = SpeechAnalyzerRecognizer(speechEnabled: { [weak app] in
            MainActor.assumeIsolated { app?.settings.speechEnabled(available: true) ?? true }
        })
        let simulated = config.debugMenu ? SimulatedSpeechRecognizer(real: recognizer) : nil
        let speech: any SpeechRecognizing = simulated.map { $0 as any SpeechRecognizing } ?? recognizer
        let debug =
            config.debugMenu
            ? DebugMenuModel(app: app, clock: debugClock, speech: simulated, preferences: preferences) : nil
        let telemetry = StudyTelemetry.make(
            config: config, app: app, transport: URLSessionTransport(),
            bundleInfo: Bundle.main.infoDictionary ?? [:],
            osMajorVersion: ProcessInfo.processInfo.operatingSystemVersion.majorVersion)
        return AppDependencies(
            config: config, app: app, audioPlayer: AVAudioPlayback(), speech: speech,
            notifications: UserNotificationScheduler(), telemetry: telemetry, debug: debug,
            review: ReviewMode(
                config: config, arguments: ProcessInfo.processInfo.arguments,
                store: try? FileReviewDraftStore.inApplicationSupport(), transport: URLSessionTransport(),
                clock: SystemClock(), ids: SystemUUIDSource()))
    }

    /// Starts sync after the learner store is open (docs/02 § Data flow at runtime): CloudKit when the build allows
    /// it, `DisabledSync` otherwise.
    func startSync() async {
        guard let store = app.store, let content = app.content else { return }
        let env = app.env
        let controller = SyncSetup.controller(
            config: config, store: store, platform: env.platform, clock: env.clock,
            openStore: { url in try await LearnerStore.open(url: url, content: content, clock: env.clock, ids: env.ids)
            },
            onStoreReplaced: { [weak app] newStore in await app?.replaceStore(newStore) })
        app.sync = controller
        let model = SyncSettingsModel(sync: controller)
        syncSettings = model
        Task { await model.observe() }
        await controller.start()
        if config.syncAllowed { SyncSetup.registerForPushes() }
    }

    /// Previews, snapshot tests and the Simulator without a pack: fakes everywhere.
    static func preview(packURL: URL) -> AppDependencies {
        AppDependencies(
            config: .preview,
            app: AppModel(
                env: .init(
                    packURL: packURL,
                    learnerURL: FileManager.default.temporaryDirectory
                        .appendingPathComponent("preview-learner.sqlite"),
                    clock: SystemClock(), ids: SystemUUIDSource(), platform: DevicePlatform.current)),
            audioPlayer: FakeAudioPlayer(), speech: FakeSpeechRecognizer(), notifications: FakeNotificationScheduler())
    }
}

/// Which device this is, for `session.platform` (docs/05).
enum DevicePlatform {
    static var current: Platform {
        #if os(macOS)
            .Mac
        #else
            UIDevice.current.userInterfaceIdiom == .pad ? .iPad : .iPhone
        #endif
    }
}
