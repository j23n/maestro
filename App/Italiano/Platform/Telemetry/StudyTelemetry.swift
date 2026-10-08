import Foundation
import LearningCore
import Observation
import Storage

/// The uploader in the app's lifecycle (task M6.5; docs/12 § Client): study builds with an endpoint and a token
/// only (`AppConfig.canUploadTelemetry`). Uploads after launch, every 15 minutes while active, when the app goes to
/// the background and after each session; every upload reads the consent and install ID from the settings at that
/// moment, so turning sharing off stops the next upload. Settings → Research's "Delete my study data" goes here too.
@MainActor
@Observable
final class StudyTelemetry {
    enum DeleteState: Equatable, Sendable {
        case idle, deleting, deleted, failed
    }

    static let defaultInterval: Duration = .seconds(15 * 60)

    @ObservationIgnored let uploader: TelemetryUploader
    @ObservationIgnored private let app: AppModel
    @ObservationIgnored private let appInfo: @MainActor () -> TelemetryAppInfo
    @ObservationIgnored private let interval: Duration
    /// One second of the uploader's backoff (tests shorten it).
    @ObservationIgnored private let backoffSecond: Duration
    @ObservationIgnored private var queue: Task<TelemetryUploader.Outcome, Never>?
    @ObservationIgnored private var periodic: Task<Void, Never>?
    /// The one-off upload after a 5xx or a network failure, when the backoff delay is over.
    @ObservationIgnored private var retry: Task<Void, Never>?
    private(set) var lastOutcome: TelemetryUploader.Outcome?
    private(set) var deleteState: DeleteState = .idle

    init(
        uploader: TelemetryUploader, app: AppModel, interval: Duration = StudyTelemetry.defaultInterval,
        backoffSecond: Duration = .seconds(1), appInfo: @escaping @MainActor () -> TelemetryAppInfo
    ) {
        self.uploader = uploader
        self.app = app
        self.interval = interval
        self.backoffSecond = backoffSecond
        self.appInfo = appInfo
    }

    /// The study build's uploader, or nil when this build never uploads. Events come from whichever learner store
    /// the app has open (an account switch replaces it). `logger` gets the batches the endpoint refuses (os.Logger in
    /// the app, `TelemetryLogger`).
    static func make(
        config: AppConfig, app: AppModel, transport: any HTTPTransport, bundleInfo: [String: Any],
        osMajorVersion: Int, logger: any CoreLogger = NoOpLogger()
    ) -> StudyTelemetry? {
        guard config.canUploadTelemetry else { return nil }
        let env = app.env
        let ids = env.ids
        let clock = env.clock
        let uploader = TelemetryUploader(
            endpoint: config.telemetryURL, token: config.studyToken,
            source: CurrentStoreEventSource { [weak app] in app?.store }, transport: transport,
            newBatchID: { ids.next() }, now: { clock.nowMs() }, logger: logger)
        let version = bundleInfo["CFBundleShortVersionString"] as? String ?? "0"
        let build = bundleInfo["CFBundleVersion"] as? String ?? "0"
        return StudyTelemetry(uploader: uploader, app: app) { [weak app] in
            TelemetryAppInfo(
                version: version, build: build, packVersion: app?.reader?.meta.packVersion ?? "",
                platform: env.platform, osMajorVersion: osMajorVersion)
        }
    }

    // MARK: Uploading

    /// Uploads what is pending, after the events written so far are stored. Calls queue up behind each other, so
    /// the same events are never in two requests at once. Without consent nothing is sent (`.notAllowed`). After a
    /// 5xx or a network failure one more upload is scheduled for when the backoff delay is over (docs/12), so the
    /// events don't wait for the next periodic upload or session.
    @discardableResult
    func uploadNow() async -> TelemetryUploader.Outcome {
        let previous = queue
        let task = Task { [app, uploader, appInfo] () -> TelemetryUploader.Outcome in
            _ = await previous?.value
            await app.settle()
            let settings = app.settings
            return await uploader.uploadPending(
                consent: settings.studyConsent, installID: settings.studyInstallId, app: appInfo())
        }
        queue = task
        let outcome = await task.value
        lastOutcome = outcome
        if case .retryLater(let seconds) = outcome {
            scheduleRetry(after: backoffSecond * max(seconds, 1))
        }
        return outcome
    }

    /// One retry at a time: a later failure while one waits leaves it as it is.
    private func scheduleRetry(after delay: Duration) {
        guard retry == nil else { return }
        retry = Task { [weak self] in
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled, let self else { return }
            self.retry = nil
            await self.uploadNow()
        }
    }

    /// A retry is waiting for its backoff delay.
    var isRetryScheduled: Bool { retry != nil }

    /// While the app is active: an upload every 15 minutes (docs/12 § Client).
    func startPeriodicUploads() {
        guard periodic == nil else { return }
        let interval = interval
        periodic = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: interval)
                guard !Task.isCancelled, let self else { return }
                await self.uploadNow()
            }
        }
    }

    func stopPeriodicUploads() {
        periodic?.cancel()
        periodic = nil
    }

    var isUploadingPeriodically: Bool { periodic != nil }

    // MARK: Delete my study data (docs/12 § Privacy and App Store)

    /// There is something to delete: an install ID exists (consent was granted at least once).
    var canDelete: Bool { app.settings.studyInstallId != nil }

    /// Turns sharing off first (so nothing uploads after the deletion), waits for an upload in flight, then asks the
    /// server to delete everything sent with this install ID. A failure leaves sharing off and can be retried.
    func deleteStudyData() async {
        guard let installID = app.settings.studyInstallId else { return }
        deleteState = .deleting
        if app.settings.studyConsent?.granted == true { app.setStudyConsent(false) }
        await app.settle()
        _ = await queue?.value
        deleteState = await uploader.deleteStudyData(installID: installID) ? .deleted : .failed
    }

    /// The line under the button.
    var deleteStatusText: String? {
        switch deleteState {
        case .idle: nil
        case .deleting: "Deleting…"
        case .deleted: "Your study data was deleted, and sharing is off."
        case .failed: "The study server couldn't be reached. Sharing is off; try again later."
        }
    }
}

/// The learner store the app has open right now, as the uploader's event source.
struct CurrentStoreEventSource: TelemetryEventSource {
    struct NoStore: Error {}

    let store: @Sendable @MainActor () -> LearnerStore?

    func unsentLocalEvents(since: Int64, limit: Int) async throws -> [StoredEvent] {
        guard let store = await store() else { return [] }
        return try await store.unsentLocalEvents(since: since, limit: limit)
    }

    func markSent(eventIDs: [String], batchID: String, at: Int64) async throws {
        guard let store = await store() else { throw NoStore() }
        try await store.markSent(eventIDs: eventIDs, batchID: batchID, at: at)
    }
}

extension TelemetryAppInfo {
    /// docs/12 § What is uploaded: the platform and device class from the device family, the OS major version only.
    init(version: String, build: String, packVersion: String, platform: Platform, osMajorVersion: Int) {
        let (name, deviceClass) =
            switch platform {
            case .iPhone: ("iOS", "phone")
            case .iPad: ("iPadOS", "tablet")
            case .Mac: ("macOS", "mac")
            }
        self.init(
            version: version, build: build, pack: packVersion, platform: name, os: String(osMajorVersion),
            deviceClass: deviceClass)
    }
}
