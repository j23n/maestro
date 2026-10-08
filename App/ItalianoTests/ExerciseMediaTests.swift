import Foundation
import LearningCore
import Testing

@testable import Italiano

@MainActor
@Suite struct ExerciseMediaTests {
    let url = URL(fileURLWithPath: "/tmp/a.m4a")

    func audio() -> (ExerciseAudio, FakeAudioPlayer) {
        let player = FakeAudioPlayer()
        let resolver = StaticAudioResolver(
            clips: ["a:1": AudioClip(audioID: "a:1", fileURL: url)], textAudio: ["u02.task.menu": "a:1"])
        return (ExerciseAudio(player: player, resolver: resolver), player)
    }

    @Test func playsOnlyWhatThePackHasAndCountsPlays() {
        let (a, player) = audio()
        #expect(!a.canPlay(nil) && !a.canPlay("a:missing") && a.canPlay("a:1"))
        #expect(!a.play("a:missing"))
        #expect(a.play("a:1", rate: PlaybackRate.slower))
        #expect(a.isPlaying("a:1") && player.rate == 0.75)
        a.toggle("a:1")
        #expect(!a.isPlaying("a:1"))
        a.toggle("a:1")
        #expect(a.plays(of: "a:1") == 2)
        #expect(a.audioID(forText: "u02.task.menu") == "a:1" && a.audioID(forText: nil) == nil)
    }

    @Test func clockAndRateLabels() {
        #expect(PlaybackClock.position(21_400, of: 62_000) == "0:21 / 1:02")
        #expect(PlaybackClock.format(-5) == "0:00" && PlaybackClock.format(600_000) == "10:00")
        #expect(PlaybackClock.rate(0.8) == "0.8×" && PlaybackClock.rate(1) == "1×")
        #expect(PlaybackClock.rate(1.15) == "1.15×")
    }

    @Test func tappingALinePlaysFromItsStart() {
        let player = FakeAudioPlayer()
        let resolver = StaticAudioResolver(
            clips: ["a:story": AudioClip(audioID: "a:story", fileURL: url)],
            timelines: [
                "a:story": [
                    TokenTiming(line: 1, index: 0, startMs: 0, endMs: 400),
                    TokenTiming(line: 2, index: 0, startMs: 1_200, endMs: 1_500),
                ]
            ])
        let a = ExerciseAudio(player: player, resolver: resolver)
        #expect(a.play("a:story", fromLine: 2))
        #expect(player.positionMs == 1_200 && a.isPlaying("a:story"))
        #expect(!a.play(nil, fromLine: 1))
    }

    @Test func captureShowsTheLiveTranscriptThenTheResult() async {
        let recognizer = FakeSpeechRecognizer(scripted: [
            SpeechResult(transcript: "vorrei un caffè", alternatives: ["vorrei un caffe"], confidence: 0.9)
        ])
        let s = SpeechCapture(recognizer: recognizer)
        let r = await s.capture(expected: Array(repeating: "x", count: 150))
        #expect(r?.transcript == "vorrei un caffè")
        #expect(s.liveTranscript == "vorrei un caffè")
        #expect(recognizer.recognizeCalls.first?.count == 100)  // contextual strings are capped
    }

    @Test func captureFailuresHaveCopy() async {
        let s = SpeechCapture(recognizer: FakeSpeechRecognizer())
        #expect(await s.capture(expected: []) == nil)
        #expect(s.state == .failed(.nothingHeard))
        #expect(s.failureMessage?.hasPrefix("I didn't hear anything") == true)
        let denied = SpeechCapture(recognizer: FakeSpeechRecognizer(availability: .denied))
        _ = await denied.capture(expected: [])
        #expect(denied.failureMessage?.contains("Settings") == true)
        denied.reset()
        #expect(denied.state == .idle && denied.failureMessage == nil)
    }

    @Test func machineFeedbackFollowsTheStates() {
        var m = FeedbackMachine(context: .lesson, exerciseHint: "Think of the article.")
        #expect(
            MachineFeedback.presentation(
                state: m.state, context: .lesson, answer: "x", rule: nil,
                canShowAnswer: true) == nil)
        _ = m.submit(GradedAnswer(outcome: .wrong))
        let hinted = MachineFeedback.presentation(
            state: m.state, context: .lesson, answer: "x", rule: nil,
            canShowAnswer: m.canShowAnswer)
        #expect(hinted?.tone == .hint && hinted?.detail == "Think of the article." && hinted?.canTryAgain == true)
        m.tryAgain()
        _ = m.submit(GradedAnswer(outcome: .wrong))
        let shown = MachineFeedback.presentation(
            state: m.state, context: .lesson, answer: "un caffè", rule: "r",
            canShowAnswer: false)
        #expect(shown?.tone == .answer && shown?.answer == "un caffè" && shown?.canContinue == true)
        #expect(
            MachineFeedback.presentation(
                state: m.state, context: .check, answer: "x", rule: nil,
                canShowAnswer: false) == nil)
    }
}
