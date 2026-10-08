import Foundation
import LearningCore
import Testing

@testable import Italiano

/// Speaking exercises appear only when the recogniser says so (docs/09 § Availability).
@MainActor
@Suite struct SpeechSettingsTests {
    let folder = FileManager.default.temporaryDirectory
        .appendingPathComponent("italiano-speech-\(UUID().uuidString)", isDirectory: true)

    func app() async -> AppModel {
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let app = AppModel(
            env: .init(
                packURL: PackAdaptersTests.packURL, learnerURL: folder.appendingPathComponent("learner.sqlite"),
                clock: FixedClock(ms: 1_791_271_800_000, tzOffsetMinutes: 120), ids: SeededUUIDSource(seed: "s"),
                platform: .iPhone))
        await app.start()
        return app
    }

    @Test func launchSetsCanSpeakFromTheRecogniser() async {
        let app = await app()
        let services = AppServices(
            config: .preview, app: app, notifications: FakeNotificationScheduler(), telemetry: nil, debug: nil,
            speech: FakeSpeechRecognizer(availability: .available))
        #expect(!app.canSpeak)
        await services.afterLaunch(arguments: [])
        #expect(app.canSpeak && services.speech?.note == nil)

        let unsupported = SpeechSettingsModel(app: app, speech: FakeSpeechRecognizer(availability: .unsupported))
        await unsupported.refresh()
        #expect(!app.canSpeak && unsupported.note == "Speaking isn't available on this device.")
        #expect(!unsupported.canDownload)
    }

    @Test func theItalianModelDownloadsOnceAndTurnsSpeakingOn() async {
        let app = await app()
        let recognizer = FakeSpeechRecognizer(availability: .needsDownload)
        let model = SpeechSettingsModel(app: app, speech: recognizer)
        await model.refresh()
        #expect(!app.canSpeak && model.canDownload && model.note?.contains("one-time download") == true)
        await model.download()
        #expect(app.canSpeak && model.availability == .available && model.downloadProgress == nil)
        await model.download()  // nothing left to download
        #expect(recognizer.downloads == 1)
    }

    @Test func switchingSpeakingOffHidesTheExercises() async {
        let app = await app()
        let model = SpeechSettingsModel(app: app, speech: SettingAwareRecognizer(app: app))
        await model.refresh()
        #expect(app.canSpeak)
        await model.setEnabled(false)
        #expect(!app.canSpeak && model.availability == .disabledInSettings && model.note == nil)
        await model.setEnabled(true)
        #expect(app.canSpeak)
    }
}

/// Reads `speech.enabled` the way `SpeechAnalyzerRecognizer` does.
@MainActor
private final class SettingAwareRecognizer: SpeechRecognizing {
    let app: AppModel
    init(app: AppModel) { self.app = app }

    func availability() async -> SpeechAvailability {
        app.settings.speechEnabled(available: true) ? .available : .disabledInSettings
    }

    func downloadAssets(progress: @escaping @MainActor (Double) -> Void) async throws {}

    func recognize(
        expected: [String], live: @escaping @MainActor (String) -> Void, recordingURL: URL?
    ) async throws -> SpeechResult {
        throw SpeechError.nothingHeard
    }

    func stop() {}
}
