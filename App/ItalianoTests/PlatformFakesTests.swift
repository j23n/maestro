import Foundation
import Testing

@testable import Italiano

/// Platform-neutral App tests (they also run on Linux through scripts/check-app-logic.sh --test).
@MainActor
@Suite struct PlatformFakesTests {
    let timings = [
        TokenTiming(line: 1, index: 0, startMs: 0, endMs: 400),
        TokenTiming(line: 1, index: 1, startMs: 450, endMs: 900),
        TokenTiming(line: 2, index: 0, startMs: 1500, endMs: 2000),
    ]

    @Test func readAlongPicksTheTokenBeingSpoken() {
        #expect(ReadAlong.token(atMs: -1, in: timings) == nil)
        #expect(ReadAlong.token(atMs: 0, in: timings) == TokenPosition(line: 1, index: 0))
        #expect(ReadAlong.token(atMs: 449, in: timings) == TokenPosition(line: 1, index: 0))
        #expect(ReadAlong.token(atMs: 450, in: timings) == TokenPosition(line: 1, index: 1))
        #expect(ReadAlong.token(atMs: 5000, in: timings) == TokenPosition(line: 2, index: 0))
        #expect(ReadAlong.lineStart(2, in: timings) == 1500)
    }

    /// M5.2: the highlight follows media time within 50 ms at 0.8× and 1× with a fake clock (30 ms observer ticks).
    @Test(arguments: [0.8, 1.0])
    func highlightDriftStaysUnder50ms(rate: Double) {
        let player = FakeAudioPlayer()
        let clip = AudioClip(audioID: "a:000000000001", fileURL: URL(fileURLWithPath: "/x.m4a"), endMs: 2500)
        player.play(clip, timeline: timings, rate: rate, context: .story)
        var worst = 0
        for t in timings {
            // advance in 30 ms ticks until the token is highlighted; measure media time past its start
            while player.currentToken != TokenPosition(line: t.line, index: t.index) && player.isPlaying {
                player.advance(byMs: 30)
            }
            worst = max(worst, player.positionMs - t.startMs)
        }
        #expect(worst < 50)
    }

    @Test func stoppingReportsWallTimePlayed() {
        let player = FakeAudioPlayer()
        var reports: [PlaybackReport] = []
        player.onStop = { reports.append($0) }
        let clip = AudioClip(
            audioID: "a:000000000002", fileURL: URL(fileURLWithPath: "/y.m4a"), endMs: 1000,
            textID: "u02.l1.story")
        player.play(clip, timeline: [], rate: 1.15, context: .fluency)
        player.advance(byMs: 300)
        player.advance(byMs: 600)  // media time 1035 ms ≥ end: stops by itself
        #expect(!player.isPlaying)
        #expect(
            reports == [
                PlaybackReport(
                    audioID: "a:000000000002", textID: "u02.l1.story", rate: 1.15,
                    playedMs: 900, context: .fluency)
            ])
    }

    @Test func wordClipsArePaddedFortyMilliseconds() {
        let clip = AudioClip.word(timings[1], audioID: "a:1", fileURL: URL(fileURLWithPath: "/z"), textID: nil)
        #expect(clip.startMs == 410 && clip.endMs == 940)
        let first = AudioClip.word(timings[0], audioID: "a:1", fileURL: URL(fileURLWithPath: "/z"), textID: nil)
        #expect(first.startMs == 0)
    }

    @Test func fakeSpeechPaths() async throws {
        let speech = FakeSpeechRecognizer(scripted: [
            SpeechResult(transcript: "vorrei un caffè", alternatives: ["vorrei un caffe"], confidence: 0.8)
        ])
        var live = ""
        let r = try await speech.recognize(expected: ["vorrei un caffè"], live: { live = $0 }, recordingURL: nil)
        #expect(r.allTranscripts == ["vorrei un caffè", "vorrei un caffe"])
        #expect(live == "vorrei un caffè")
        await #expect(throws: SpeechError.nothingHeard) {
            try await speech.recognize(expected: [], live: { _ in }, recordingURL: nil)
        }
        speech.typed = "quant'è"
        #expect(try await speech.recognize(expected: [], live: { _ in }, recordingURL: nil).transcript == "quant'è")
        let unavailable = FakeSpeechRecognizer(availability: .unsupported)
        await #expect(throws: SpeechError.unavailable(.unsupported)) {
            try await unavailable.recognize(expected: [], live: { _ in }, recordingURL: nil)
        }
        let download = FakeSpeechRecognizer(availability: .needsDownload)
        try await download.downloadAssets { _ in }
        #expect(await download.availability() == .available)
    }

    @Test func remindersAskPermissionOnlyWhenTurnedOn() async {
        let fake = FakeNotificationScheduler()
        let controller = ReminderController(scheduler: fake)
        #expect(fake.permissionRequests == 0)
        #expect(await controller.apply(enabled: false, time: .defaultTime) == false)
        #expect(fake.permissionRequests == 0 && fake.cancels == 1)
        #expect(await controller.apply(enabled: true, time: ReminderTime(hour: 8, minute: 30)))
        #expect(fake.permissionRequests == 1)
        #expect(fake.scheduled == [ReminderTime(hour: 8, minute: 30)])
        #expect(await controller.apply(enabled: true, time: ReminderTime(hour: 9, minute: 0)))
        #expect(fake.permissionRequests == 1)  // already authorised: never asked twice
        #expect(fake.scheduled == [ReminderTime(hour: 9, minute: 0)])
    }

    @Test func deniedPermissionTurnsRemindersOff() async {
        let controller = ReminderController(scheduler: FakeNotificationScheduler(grants: false))
        #expect(await controller.apply(enabled: true, time: .defaultTime) == false)
        #expect(controller.lastOutcome == .permissionDenied)
    }

    @Test func reminderTimeParsing() {
        #expect(ReminderTime("07:45") == ReminderTime(hour: 7, minute: 45))
        #expect(ReminderTime("24:00") == nil)
        #expect(ReminderTime(hour: 7, minute: 5).text == "07:05")
    }

    @Test func appConfigFromInfoKeys() {
        let study = AppConfig(info: [
            "ITA_STUDY_BUILD": "YES", "ITA_TELEMETRY_URL": "https://study.example.org",
            "ITA_STUDY_TOKEN": "t", "ITA_LLM_HINTS": "YES", "ITA_PACK": "release",
        ])
        #expect(study.canUploadTelemetry)
        #expect(!study.llmHints)  // ADR-10: never in study builds
        #expect(study.pack == .release)
        let unsetToken = AppConfig(info: [
            "ITA_STUDY_BUILD": "YES", "ITA_TELEMETRY_URL": "https://x.org",
            "ITA_STUDY_TOKEN": "$(ITA_STUDY_TOKEN)",
        ])
        #expect(!unsetToken.canUploadTelemetry)  // an unexpanded build setting is no token
        let debug = AppConfig(info: ["ITA_DEBUG_MENU": "YES", "ITA_SYNC_ENABLED": "YES"])
        #expect(debug.debugMenu)
        #expect(!debug.syncAllowed(hasICloudEntitlement: false))
        #expect(debug.syncAllowed(hasICloudEntitlement: true))
        #expect(
            !AppConfig(info: ["ITA_REVIEW_MODE": "YES", "ITA_SYNC_ENABLED": "YES"]).syncAllowed(
                hasICloudEntitlement: true))
    }
}
