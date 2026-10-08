import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// An app on the mini pack (Units 0–2) with a throwaway learner database, for the app-shell tests.
@MainActor
struct ShellTestApp {
    let folder = FileManager.default.temporaryDirectory
        .appendingPathComponent("italiano-shell-\(UUID().uuidString)", isDirectory: true)
    /// Tue 6 Oct 2026, 09:30 in Rome.
    let base = FixedClock(ms: 1_791_271_800_000, tzOffsetMinutes: 120)

    func model(_ seed: String = "a", clock: (any LearningCore.Clock)? = nil) -> AppModel {
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return AppModel(
            env: .init(
                packURL: PackAdaptersTests.packURL, learnerURL: folder.appendingPathComponent("learner.sqlite"),
                clock: clock ?? base, ids: SeededUUIDSource(seed: seed), platform: .iPhone))
    }

    func started(
        _ seed: String = "a", clock: (any LearningCore.Clock)? = nil, content: ContentIndex? = nil
    ) async -> AppModel {
        let app = model(seed, clock: clock)
        await app.start(content: content)
        return app
    }

    func events(_ app: AppModel) async throws -> [Event] {
        try await #require(app.store).events()
    }

    /// Lets the store's state stream reach the model (rebuilds and resets publish through it).
    func caughtUp(_ app: AppModel, sourceLocation: SourceLocation = #_sourceLocation) async throws {
        try await waitUntil("the store's state reaches the app model", sourceLocation: sourceLocation) {
            app.state == app.store?.state
        }
    }
}

/// Waits for work the app does on its own tasks (state streams, uploads after a session) until `condition` holds;
/// after `timeout` the test fails here, saying what never happened, instead of at a later, unrelated expectation.
@MainActor
func waitUntil(
    _ what: String, timeout: Duration = .seconds(10), sourceLocation: SourceLocation = #_sourceLocation,
    _ condition: () -> Bool
) async throws {
    let clock = ContinuousClock()
    let deadline = clock.now.advanced(by: timeout)
    while !condition(), clock.now < deadline {
        try await Task.sleep(for: .milliseconds(5))
    }
    try #require(condition(), "timed out after \(timeout): \(what)", sourceLocation: sourceLocation)
}

/// `DebugPreferences` in memory.
@MainActor
final class MemoryPreferences: DebugPreferences {
    var values: [String: Any] = [:]
    func integer(forKey key: String) -> Int { values[key] as? Int ?? 0 }
    func bool(forKey key: String) -> Bool { values[key] as? Bool ?? false }
    func set(_ value: Int, forKey key: String) { values[key] = value }
    func set(_ value: Bool, forKey key: String) { values[key] = value }
}

/// A sync controller that only records what it is asked.
final class RecordingSync: SyncControlling, @unchecked Sendable {
    // @unchecked: test double; `resets` is guarded by `lock`.
    private let lock = NSLock()
    private var _resets = 0
    var resets: Int { lock.withLock { _resets } }

    func snapshots() async -> AsyncStream<SyncSnapshot> { AsyncStream { $0.finish() } }
    func start() async {}
    func syncNow() async {}
    func setPaused(_ paused: Bool) async {}
    func resolveAccountSwitch(confirm: Bool) async {}
    func dismissNotice() async {}
    func resetProgress() async { lock.withLock { _resets += 1 } }
}

/// M3.3: the Debug menu (docs/02 § App configuration) and `-ITAJumpToUnit`.
@MainActor
@Suite struct DebugMenuTests {
    let shell = ShellTestApp()

    @Test func launchArguments() {
        #expect(LaunchArguments(["/app", "-ITAJumpToUnit", "u02"]).jumpToUnit == "u02")
        #expect(LaunchArguments(["-ITAJumpToUnit", "2"]).jumpToUnit == "u02")
        #expect(LaunchArguments(["-ITAJumpToUnit", "U12"]).jumpToUnit == "u12")
        #expect(LaunchArguments(["-ITAJumpToUnit", "u01", "-ITAJumpToUnit", "u02"]).jumpToUnit == "u02")
        #expect(LaunchArguments(["-ITAJumpToUnit"]).jumpToUnit == nil)
        #expect(LaunchArguments(["-ITAJumpToUnit", "bar"]).jumpToUnit == nil)
        #expect(LaunchArguments(["-ITAJumpToUnit", "u+2"]).jumpToUnit == nil)
        #expect(LaunchArguments(["-ITAJumpToUnit", "u123"]).jumpToUnit == nil)
        #expect(LaunchArguments(["-NSDoubleLocalizedStrings", "YES"]) == LaunchArguments())
    }

    @Test func jumpingToAUnitWritesAPlacementStyleIntroduction() async throws {
        let app = await shell.started()
        let content = try #require(app.content)
        let written = try await app.debugJump(to: "u02")
        #expect(written == 2)
        let state = try #require(app.state)
        #expect(state.placement?.startUnit == "u02")
        #expect(state.units["u00"]?.state == .skipped && state.units["u01"]?.state == .skipped)
        #expect(state.units["u02"]?.state == .available)
        // Every item of Units 0 and 1, per its status, introduced via `debug`; nothing of Unit 2; no memory.
        let expected = try #require(Introductions.placementPayload(startUnit: "u02", content: content)).pairs
        #expect(!expected.isEmpty)
        #expect(expected.allSatisfy { state.introductions[$0]?.via == .debug })
        #expect(!state.introductions.keys.contains { content.item($0.itemId)?.unitId == "u02" })
        #expect(state.memory.isEmpty)
        let types = try await shell.events(app).map(\.type)
        #expect(types == ["placementCompleted", "introduced"])
        #expect(app.today?.continueCard?.unitID == "u02")

        // Again: nothing left to write.
        #expect(try await app.debugJump(to: "u02") == 0)
        await #expect(throws: AppModel.DebugError.unknownUnit("u42")) { try await app.debugJump(to: "u42") }
        // Back to the beginning: a new placement, no introductions to add.
        #expect(try await app.debugJump(to: "u00") == 1)
        #expect(app.state?.units["u00"]?.state == .available)
    }

    @Test func theLaunchArgumentOnboardsJumpsAndIsIdempotent() async throws {
        let first = await shell.started()
        #expect(!first.isOnboarded)
        let services = AppServices(
            config: .preview, app: first, notifications: FakeNotificationScheduler(), telemetry: nil,
            debug: DebugMenuModel(app: first, clock: nil, speech: nil, preferences: MemoryPreferences()))
        await services.afterLaunch(arguments: ["/app", "-ITAJumpToUnit", "u02"])
        #expect(first.isOnboarded && first.settings.profileForms == .both)
        #expect(first.state?.placement?.startUnit == "u02")
        let count = try await shell.events(first).count
        #expect(try await shell.events(first).map(\.type).contains("onboardingCompleted"))
        #expect(services.debug?.status == "Launched at u02")

        // Relaunch with the same argument (the M3.6 resume test): nothing new is written.
        let again = await shell.started("b")
        #expect(again.isOnboarded)
        let relaunch = AppServices(
            config: .preview, app: again, notifications: FakeNotificationScheduler(), telemetry: nil,
            debug: DebugMenuModel(app: again, clock: nil, speech: nil, preferences: MemoryPreferences()))
        await relaunch.afterLaunch(arguments: ["-ITAJumpToUnit", "u02"])
        #expect(try await shell.events(again).count == count)
    }

    /// With a pack that can run placement, the launch argument's onboarding ("Yes, I know a little" for any unit
    /// but the first) offers placement; the jump places the learner, so the app opens on Today (docs/02), and the
    /// Debug menu's Jump withdraws an offer too. The mini pack has no placement questions: the synthetic course does.
    @Test func jumpingWithdrawsThePlacementOffer() async throws {
        let app = await shell.started(content: AssessmentCourse.content)
        #expect(app.canRunPlacement && !app.isOnboarded)
        let debug = DebugMenuModel(app: app, clock: nil, speech: nil, preferences: MemoryPreferences())
        let services = AppServices(
            config: .preview, app: app, notifications: FakeNotificationScheduler(), telemetry: nil, debug: debug)
        await services.afterLaunch(arguments: ["-ITAJumpToUnit", "u02"])
        #expect(debug.status == "Launched at u02")
        #expect(app.isOnboarded && app.state?.placement?.startUnit == "u02")
        #expect(!app.placementPending)  // RootView shows the tabs, not PlacementHost

        app.offerPlacement(beginner: false)
        #expect(app.placementPending)
        debug.jumpTarget = "u03"
        await debug.jump()
        #expect(debug.status == "Jumped to u03 · 2 events")
        #expect(!app.placementPending && app.state?.placement?.startUnit == "u03")
    }

    @Test func releaseBuildsIgnoreTheLaunchArgumentAndHaveNoDebugMenu() async throws {
        let app = await shell.started()
        let release = AppConfig(info: ["ITA_DEBUG_MENU": "NO"])
        let services = AppServices(
            config: release, app: app, notifications: FakeNotificationScheduler(), telemetry: nil,
            debug: DebugMenuModel(app: app, clock: nil, speech: nil, preferences: MemoryPreferences()))
        #expect(services.debug == nil)
        await services.afterLaunch(arguments: ["-ITAJumpToUnit", "u02"])
        #expect(try await shell.events(app).isEmpty)
        #expect(!app.isOnboarded)
    }

    @Test func theClockOffsetMovesTodayAndIsKept() async throws {
        let preferences = MemoryPreferences()
        let clock = DebugClock(base: shell.base, offsetDays: DebugMenuModel.storedClockOffset(preferences))
        let app = await shell.started(clock: clock)
        let debug = DebugMenuModel(app: app, clock: clock, speech: nil, preferences: preferences)
        #expect(app.today?.dateLine == "Tuesday, October 6")
        debug.setClockOffset(days: 2)
        #expect(app.today?.dateLine == "Thursday, October 8")
        #expect(debug.clockOffsetDays == 2 && debug.status == "Clock: +2 days")
        #expect(clock.nowMs() == shell.base.nowMs() + 2 * 86_400_000)
        // Events written now carry the shifted time.
        try await app.debugJump(to: "u01")
        #expect(try await shell.events(app).first?.at == clock.nowMs())
        // The next launch starts with the same offset.
        #expect(DebugMenuModel.storedClockOffset(preferences) == 2)
        debug.setClockOffset(days: -1)
        #expect(app.today?.dateLine == "Monday, October 5" && debug.status == "Clock: -1 days")
    }

    @Test func rebuildExportAndReset() async throws {
        let app = await shell.started()
        let exportFolder = shell.folder.appendingPathComponent("exports")
        let debug = DebugMenuModel(
            app: app, clock: nil, speech: nil, preferences: MemoryPreferences(), exportFolder: exportFolder)
        try await app.debugJumpAtLaunch(to: "u02")
        let before = try #require(app.state)

        await debug.rebuild()
        let events = try await shell.events(app).count
        #expect(debug.status == "Rebuilt from \(events) events")
        try await shell.caughtUp(app)
        #expect(app.state == before)

        await debug.exportDatabase()
        let file = try #require(debug.exportedFile)
        #expect(file.lastPathComponent == "learner-2026-10-06.sqlite")
        let copy = try await LearnerStore.open(
            url: file, content: try #require(app.content), clock: shell.base, ids: SeededUUIDSource(seed: "x"))
        #expect(try await copy.eventCount() == events)
        try copy.close()
        // The exporter saved (or the learner cancelled): the temporary copy is deleted.
        debug.exportFinished()
        #expect(debug.exportedFile == nil)
        #expect(!FileManager.default.fileExists(atPath: file.path))

        // Sync off in this build: the store erases this device's progress; onboarding runs again.
        app.sync = DisabledSync()
        _ = try await app.store?.set(.displayTextScale, to: .number(1.3))
        await debug.resetLocalData()
        #expect(debug.status == "Local data reset")
        #expect(try await shell.events(app).isEmpty)
        try await shell.caughtUp(app)
        #expect(app.state?.introductions.isEmpty == true)
        #expect(!app.isOnboarded)
        #expect(app.store?.settings.textScale == 1.3)  // device settings stay
    }

    @Test func resetGoesThroughSyncWhenItRuns() async throws {
        let app = await shell.started()
        try await app.debugJump(to: "u02")
        let sync = RecordingSync()
        app.sync = sync
        try await app.debugResetLocalData()
        #expect(sync.resets == 1)
    }

    @Test func eligibilityAndDraftMarkersForTheOverlay() async throws {
        let app = await shell.started()
        let debug = DebugMenuModel(app: app, clock: nil, speech: nil, preferences: MemoryPreferences())
        await debug.load()
        #expect(debug.draftSteps.contains("u02.l1.step-story"))  // the mini pack is a dev pack of drafts
        #expect(debug.jumpTarget == "u00" && debug.units.map(\.id) == ["u00", "u01", "u02"])
        #expect(!debug.isDraft("u02.l1.step-story"))  // markers off
        #expect(debug.eligibility(step: "u02.l1.step-story", exercise: "u02.l1.ex04").isEmpty)

        debug.showDraftMarkers = true
        debug.showEligibility = true
        #expect(debug.isDraft("u02.l1.step-story") && !debug.isDraft(nil))
        try await app.debugJump(to: "u02")
        let reports = debug.eligibility(step: "u02.l1.step-practice", exercise: "u02.l1.ex04")
        #expect(reports.map(\.title) == ["Step u02.l1.step-practice", "Exercise u02.l1.ex04"])
        let exercise = try #require(reports.last)
        #expect(exercise.summary == "2 required · 2 missing" && !exercise.isEligible)
        #expect(
            exercise.requirements.map(\.line) == [
                "g:indefinite-article · recall · MISSING", "w:cornetto · recall · MISSING",
            ])
        // Generated review cards aren't in the pack: no exercise report.
        #expect(debug.eligibility(step: nil, exercise: "gen:recall:w:cornetto").isEmpty)
        // The switches are kept for the next launch.
        let preferences = MemoryPreferences()
        let kept = DebugMenuModel(app: app, clock: nil, speech: nil, preferences: preferences)
        kept.showEligibility = true
        #expect(DebugMenuModel(app: app, clock: nil, speech: nil, preferences: preferences).showEligibility)
    }

    @Test func simulatedSpeechAsksForTypedText() async throws {
        let app = await shell.started()
        let real = FakeSpeechRecognizer(availability: .unsupported)
        let speech = SimulatedSpeechRecognizer(real: real)
        let debug = DebugMenuModel(app: app, clock: nil, speech: speech, preferences: MemoryPreferences())
        #expect(await speech.availability() == .unsupported)
        await #expect(throws: SpeechError.unavailable(.unsupported)) {
            try await speech.recognize(expected: ["un caffè"], live: { _ in }, recordingURL: nil)
        }

        await debug.setSimulateSpeech(true)
        #expect(app.canSpeak && debug.simulateSpeech)
        #expect(await speech.availability() == .available)
        let capture = SpeechCapture(recognizer: speech)
        let answer = Task { await capture.capture(expected: ["un caffè", "un caffè, per favore"]) }
        while speech.prompt == nil { await Task.yield() }
        #expect(speech.prompt?.expected == ["un caffè", "un caffè, per favore"])
        speech.submit("  un caffè ")
        #expect(await answer.value?.transcript == "un caffè")
        #expect(speech.prompt == nil)

        // Cancel (or stop) leaves the capture idle, as a real cancelled recording does.
        let cancelled = Task { await capture.capture(expected: ["sì"]) }
        while speech.prompt == nil { await Task.yield() }
        speech.stop()
        #expect(await cancelled.value == nil && capture.state == .idle)

        // Switched off: the real recogniser again, and a waiting prompt is cancelled.
        let waiting = Task { await capture.capture(expected: ["no"]) }
        while speech.prompt == nil { await Task.yield() }
        await debug.setSimulateSpeech(false)
        #expect(await waiting.value == nil && speech.prompt == nil)
        #expect(!app.canSpeak && real.recognizeCalls.count == 1)
    }
}
