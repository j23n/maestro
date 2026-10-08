import Foundation
import LearningCore
import Observation

/// Whether speaking exercises appear (docs/09 § Availability): asks the recogniser at launch, whenever the app
/// becomes active (microphone access may have changed in system settings) and when the learner switches
/// "Speaking exercises", and sets `AppModel.canSpeak` from the answer. Offers the one-time download of the
/// Italian model. Platform-neutral and tested with `FakeSpeechRecognizer`.
@MainActor
@Observable
final class SpeechSettingsModel {
    private(set) var availability: SpeechAvailability?
    /// 0…1 while the Italian model downloads; nil otherwise.
    private(set) var downloadProgress: Double?
    private(set) var downloadFailed = false

    @ObservationIgnored let app: AppModel
    @ObservationIgnored let speech: any SpeechRecognizing

    init(app: AppModel, speech: any SpeechRecognizing) {
        self.app = app
        self.speech = speech
    }

    func refresh() async {
        let now = await speech.availability()
        availability = now
        app.canSpeak = now.canSpeak
    }

    /// "Speaking exercises" (`speech.enabled`, device-scoped): the recogniser reads the setting, so the answer is
    /// asked again once the write has landed.
    func setEnabled(_ on: Bool) async {
        app.set(.speechEnabled, to: .bool(on))
        await app.settle()
        await refresh()
    }

    var canDownload: Bool { availability == .needsDownload && downloadProgress == nil }

    func download() async {
        guard canDownload else { return }
        downloadFailed = false
        downloadProgress = 0
        do {
            try await speech.downloadAssets { [weak self] p in self?.downloadProgress = min(max(p, 0), 1) }
        } catch {
            downloadFailed = true
        }
        downloadProgress = nil
        await refresh()
    }

    /// The line under the switch (docs/09: "Speaking isn't available on this device").
    var note: String? {
        if downloadFailed { return "The download didn't finish. Check your connection and try again." }
        switch availability {
        case .unsupported: return "Speaking isn't available on this device."
        case .needsDownload: return "Speaking exercises need Italian speech recognition, a one-time download."
        case .denied: return "Italiano can't use the microphone. Turn it on in the system's Settings → Privacy."
        case .available, .disabledInSettings, nil: return nil
        }
    }
}
