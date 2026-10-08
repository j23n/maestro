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
    /// Settings → Sync and the account-switch alert; set once sync starts.
    private(set) var syncSettings: SyncSettingsModel?

    init(
        config: AppConfig, app: AppModel, audioPlayer: any AudioPlaying, speech: any SpeechRecognizing,
        notifications: any NotificationScheduling
    ) {
        self.config = config
        self.app = app
        self.audioPlayer = audioPlayer
        self.speech = speech
        self.notifications = notifications
    }

    /// The real app: the bundled pack (`Resources/Content/content.sqlite`), the learner database in Application
    /// Support, AVFoundation playback, SpeechAnalyzer and UserNotifications.
    static func live() -> AppDependencies {
        let config = AppConfig.fromMainBundle()
        let packURL =
            Bundle.main.url(forResource: "content", withExtension: "sqlite", subdirectory: "Content")
            ?? Bundle.main.bundleURL.appendingPathComponent("Content/content.sqlite")
        let app = AppModel(
            env: .init(
                packURL: packURL, learnerURL: nil, clock: SystemClock(), ids: SystemUUIDSource(),
                platform: DevicePlatform.current))
        return AppDependencies(
            config: config, app: app, audioPlayer: AVAudioPlayback(),
            speech: SpeechAnalyzerRecognizer(speechEnabled: { [weak app] in
                MainActor.assumeIsolated { app?.settings.speechEnabled(available: true) ?? true }
            }),
            notifications: UserNotificationScheduler())
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
