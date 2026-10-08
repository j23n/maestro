import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// M6.5: the uploader in the app's lifecycle, against a mock server and the real learner store (docs/12).
@MainActor
@Suite struct StudyTelemetryTests {
    typealias Server = TelemetryUploaderTests.Server

    let shell = ShellTestApp()
    static let study = AppConfig(info: [
        "ITA_STUDY_BUILD": "YES", "ITA_TELEMETRY_URL": "https://study.example.org", "ITA_STUDY_TOKEN": "tok",
    ])
    static let bundle: [String: Any] = ["CFBundleShortVersionString": "0.9.0", "CFBundleVersion": "57"]

    func telemetry(_ app: AppModel, _ server: Server, config: AppConfig = Self.study) -> StudyTelemetry? {
        StudyTelemetry.make(config: config, app: app, transport: server, bundleInfo: Self.bundle, osMajorVersion: 26)
    }

    /// The batch requests (DELETEs and other requests left out).
    func batches(_ server: Server) -> [[String: Any]] {
        zip(server.requests, server.bodies()).compactMap { $0.0.method == "POST" ? $0.1 : nil }
    }

    @Test func onlyStudyBuildsThatCanUploadGetAnUploader() async {
        let app = await shell.started()
        #expect(telemetry(app, Server([])) != nil)
        #expect(telemetry(app, Server([]), config: .preview) == nil)
        let noToken = AppConfig(info: ["ITA_STUDY_BUILD": "YES", "ITA_TELEMETRY_URL": "https://study.example.org"])
        #expect(telemetry(app, Server([]), config: noToken) == nil)
        let services = AppServices(
            config: Self.study, app: app, notifications: FakeNotificationScheduler(), telemetry: nil,
            debug: DebugMenuModel(app: app, clock: nil, speech: nil, preferences: MemoryPreferences()))
        #expect(services.debug == nil)  // study builds have no Debug menu
    }

    @Test func nothingIsSentWithoutConsentThenOnlyEventsFromTheConsentDate() async throws {
        let app = await shell.started()
        let server = Server([])
        let study = try #require(telemetry(app, server))
        try await app.debugJump(to: "u01")  // events before any consent
        #expect(await study.uploadNow() == .notAllowed)
        #expect(server.requests.isEmpty)

        shell.base.advance(byMs: 60_000)
        app.setStudyConsent(true)
        await app.settle()
        #expect(await study.uploadNow() == .nothingToSend)  // the earlier events predate consent
        try await app.debugJump(to: "u02")
        #expect(await study.uploadNow() == .sent(events: 2, batches: 1))
        let body = try #require(batches(server).last)
        #expect(body["installId"] as? String == app.settings.studyInstallId)
        let info = try #require(body["app"] as? [String: Any])
        #expect(info["version"] as? String == "0.9.0" && info["build"] as? String == "57")
        #expect(info["platform"] as? String == "iOS" && info["deviceClass"] as? String == "phone")
        #expect(info["os"] as? String == "26" && info["pack"] as? String == app.reader?.meta.packVersion)
        #expect(
            (body["events"] as? [[String: Any]])?.map { $0["type"] as? String } == ["placementCompleted", "introduced"])
        #expect(await study.uploadNow() == .nothingToSend)  // marked sent in the store

        // Sharing off: uploads stop at once.
        app.setStudyConsent(false)
        try await app.debugJump(to: "u00")
        #expect(await study.uploadNow() == .notAllowed)
        #expect(batches(server).count == 1)
    }

    @Test func launchSessionsAndBackgroundUpload() async throws {
        let app = await shell.started()
        let server = Server([])
        let study = try #require(telemetry(app, server))
        app.setStudyConsent(true)
        try await app.debugJump(to: "u01")
        let services = AppServices(
            config: Self.study, app: app, notifications: FakeNotificationScheduler(), telemetry: study, debug: nil)

        await services.afterLaunch(arguments: [])
        #expect(batches(server).count == 1)
        #expect(study.isUploadingPeriodically)

        // A finished session uploads its event.
        app.endSession(sessionID: "s1", kind: .review, startedAt: shell.base.nowMs(), activeSeconds: 30)
        try await waitUntil("the session's upload reaches the server") { batches(server).count >= 2 }
        let sessionBatch = try #require(batches(server).last?["events"] as? [[String: Any]])
        #expect(sessionBatch.map { $0["type"] as? String } == ["session"])

        // Background: periodic uploads stop and what is pending goes.
        try await app.debugJump(to: "u02")
        services.activityChanged(.background)
        #expect(!study.isUploadingPeriodically)
        try await waitUntil("the background upload reaches the server") { batches(server).count >= 3 }
        #expect(batches(server).count == 3)
        services.activityChanged(.active)
        #expect(study.isUploadingPeriodically)
        study.stopPeriodicUploads()
    }

    @Test func periodicUploadsRunWhileActive() async throws {
        let app = await shell.started()
        let server = Server([])
        let env = app.env
        let study = StudyTelemetry(
            uploader: TelemetryUploader(
                endpoint: URL(string: "https://study.example.org"), token: "tok",
                source: CurrentStoreEventSource { [weak app] in app?.store }, transport: server,
                newBatchID: { env.ids.next() }, now: { env.clock.nowMs() }),
            app: app, interval: .milliseconds(10)
        ) {
            TelemetryAppInfo(version: "1", build: "1", packVersion: "p", platform: .Mac, osMajorVersion: 26)
        }
        app.setStudyConsent(true)
        try await app.debugJump(to: "u01")
        study.startPeriodicUploads()
        try await waitUntil("a periodic upload reaches the server") { !batches(server).isEmpty }
        study.stopPeriodicUploads()
        let info = try #require(batches(server).first?["app"] as? [String: Any])
        #expect(info["platform"] as? String == "macOS" && info["deviceClass"] as? String == "mac")
    }

    /// A 5xx or a network failure: one more upload runs when the backoff delay is over, without waiting for the
    /// next 15-minute upload or session (docs/12). A second of backoff is a millisecond here.
    @Test func aFailedUploadIsRetriedAfterTheBackoff() async throws {
        let app = await shell.started()
        let server = Server([503, 503])
        let env = app.env
        let study = StudyTelemetry(
            uploader: TelemetryUploader(
                endpoint: URL(string: "https://study.example.org"), token: "tok",
                source: CurrentStoreEventSource { [weak app] in app?.store }, transport: server,
                newBatchID: { env.ids.next() }, now: { env.clock.nowMs() }),
            app: app, backoffSecond: .milliseconds(1)
        ) {
            TelemetryAppInfo(version: "1", build: "1", packVersion: "p", platform: .iPhone, osMajorVersion: 26)
        }
        app.setStudyConsent(true)
        try await app.debugJump(to: "u01")
        #expect(await study.uploadNow() == .retryLater(afterSeconds: 60))
        #expect(study.isRetryScheduled && server.requests.count == 1)

        // The device clock moves past the backoff: the scheduled retry asks again (503 again: 120 s more), then
        // the one after that gets through.
        shell.base.advance(byMs: 60_000)
        try await waitUntil("the first retry reaches the server") { server.requests.count >= 2 }
        try await waitUntil("the first retry's outcome") { study.lastOutcome == .retryLater(afterSeconds: 120) }
        #expect(study.isRetryScheduled)
        shell.base.advance(byMs: 120_000)
        try await waitUntil("the second retry is sent") { study.lastOutcome == .sent(events: 2, batches: 1) }
        #expect(!study.isRetryScheduled && server.requests.count == 3)
    }

    @Test func deletingStudyDataTurnsSharingOffAndAsksTheServer() async throws {
        let app = await shell.started()
        let server = Server([204])
        let study = try #require(telemetry(app, server))
        #expect(!study.canDelete)
        app.setStudyConsent(true)
        await app.settle()
        let installID = try #require(app.settings.studyInstallId)
        #expect(study.canDelete)

        await study.deleteStudyData()
        #expect(study.deleteState == .deleted && study.deleteStatusText != nil)
        #expect(app.settings.studyConsent?.granted == false)
        let request = try #require(server.requests.last)
        #expect(request.method == "DELETE")
        #expect(request.url.absoluteString == "https://study.example.org/v1/installs/\(installID)")

        // The server can't be reached: sharing stays off and the button can be tried again.
        server.failNetwork = true
        await study.deleteStudyData()
        #expect(study.deleteState == .failed && app.settings.studyConsent?.granted == false)
        #expect(study.canDelete)
    }

    @Test func appInfoPerPlatform() {
        let pad = TelemetryAppInfo(version: "1", build: "2", packVersion: "0.6.0", platform: .iPad, osMajorVersion: 26)
        #expect(
            pad
                == TelemetryAppInfo(
                    version: "1", build: "2", pack: "0.6.0", platform: "iPadOS", os: "26", deviceClass: "tablet"))
    }
}
