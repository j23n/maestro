import Foundation
import LearningCore
import Testing

@testable import Italiano

@MainActor
@Suite struct TappedExerciseModelTests {
    let sink = RecordingAttemptSink()

    func env(_ context: AttemptContext = .lesson, canSpeak: Bool = false) -> ExerciseEnvironment {
        var e = ExerciseEnvironment.preview(context: context)
        e.canSpeak = canSpeak
        return e
    }

    @Test func choiceWrongThenRight() throws {
        let m = try #require(ChoiceModel(payload: try PayloadFixtures.exercise("u02.l1.ex17"), env: env(), sink: sink))
        #expect(m.options.map(\.id).sorted() == [0, 1, 2])
        #expect(m.options.allSatisfy { $0.italian != nil })  // Italian options are tappable ItalianText
        m.select(1)
        #expect(m.markedWrong == [1])
        #expect(m.hint == "Use Lei with someone you don't know, and an adjective that agrees with her.")
        m.select(1)  // a marked option can't be picked again
        #expect(sink.drafts.count == 1)
        m.select(0)
        #expect(m.isDone)
        #expect(sink.drafts.map(\.attemptIndex) == [1, 2])
        #expect(sink.drafts.map(\.outcome) == [.wrong, .correct])
        #expect(sink.drafts[0].mode == .tapped)
    }

    @Test func soundPairsAndTrueFalseUseTheirOwnAnswers() throws {
        let which = try #require(
            ChoiceModel(payload: try PayloadFixtures.exercise("u02.l1.ex22"), env: env(), sink: sink))
        #expect(which.correctIndex == 1 && which.options.map(\.text) == ["eco", "ecco"])
        let single = try #require(
            ChoiceModel(payload: try PayloadFixtures.exercise("u02.l1.ex23"), env: env(), sink: sink))
        #expect(single.correctIndex == 1)  // double
        let tf = try #require(
            ChoiceModel(payload: try PayloadFixtures.exercise("u02.check.03"), env: env(.check), sink: sink))
        tf.select(1)
        #expect(tf.isDone && sink.drafts.last?.outcome == .wrong)
        #expect(tf.mark(for: tf.options[0]) == .idle)  // no feedback in checks
    }

    @Test func matchGivesEachPairItsOwnFirstTryOutcome() throws {
        let m = try #require(MatchModel(payload: try PayloadFixtures.exercise("u02.l1.ex20"), env: env(), sink: sink))
        m.tapLeft(0)
        m.tapRight(1)  // wrong
        m.tapLeft(0)
        m.tapRight(0)
        m.tapLeft(1)
        m.tapRight(1)
        #expect(m.isDone)
        let d = try #require(sink.drafts.last)
        #expect(d.targets.map(\.outcome) == [.wrong, .correct])
        #expect(d.outcome == .wrong && d.attemptIndex == 1)
    }

    @Test func matchInACheckIsSubmittedOnce() throws {
        let m = try #require(
            MatchModel(payload: try PayloadFixtures.exercise("u02.l1.ex20"), env: env(.check), sink: sink))
        m.tapLeft(0)
        m.tapRight(0)
        m.tapLeft(1)
        m.tapRight(0)
        m.submitAssessment()
        #expect(sink.drafts.last?.targets.map(\.outcome) == [.correct, .wrong])
    }

    @Test func sentenceBuilding() throws {
        let m = try #require(
            SentenceBuildingModel(payload: try PayloadFixtures.exercise("u02.l1.ex10"), env: env(), sink: sink))
        #expect(m.tiles.map(\.word).joined(separator: " ") != "oggi vorrei un caffè")
        for word in ["oggi", "vorrei", "una", "caffè"] {
            m.place(try #require(m.available.first { $0.word == word }).id)
        }
        m.check()
        #expect(m.highlighted == m.answerLine[2].id)  // the first misplaced tile
        let una = m.answerLine[2].id
        m.remove(una)
        m.remove(m.answerLine[2].id)
        m.place(try #require(m.available.first { $0.word == "un" }).id)
        m.place(try #require(m.available.first { $0.word == "caffè" }).id)
        m.check()
        #expect(m.isDone)
        #expect(m.displayedSentence == "Oggi vorrei un caffè.")
        #expect(sink.drafts.map(\.outcome) == [.wrong, .correct])
    }

    @Test func sentenceBuildingInACheckHighlightsNothing() throws {
        let m = try #require(
            SentenceBuildingModel(payload: try PayloadFixtures.exercise("u02.l1.ex10"), env: env(.check), sink: sink))
        for word in ["oggi", "vorrei", "una", "caffè"] {
            m.place(try #require(m.available.first { $0.word == word }).id)
        }
        m.check()
        #expect(m.isDone)
        #expect(m.highlighted == nil)
        #expect(sink.drafts.map(\.outcome) == [.wrong])
    }

    @Test func dictationMarksDoubling() throws {
        let m = try #require(
            DictationModel(payload: try PayloadFixtures.exercise("u02.l1.ex13"), env: env(), sink: sink))
        #expect(m.hintLine == "5 words")
        m.response = "vorrei un corneto per favore"
        m.check()
        #expect(m.result?.outcome == .almost)
        #expect(m.doublingNote == "Listen again: cornetto has a double t.")
        #expect(sink.drafts.last?.outcome == .almost)
    }

    @Test func repeatPassesOnTheTranscriptAndSkipsCleanly() throws {
        let m = try #require(
            RepeatModel(payload: try PayloadFixtures.exercise("u02.l1.ex14"), env: env(canSpeak: true), sink: sink))
        m.submit(SpeechResult(transcript: "vorrei un caffè", alternatives: [], confidence: nil))
        #expect(m.passed == false && m.heard == "vorrei un caffè")
        m.submit(SpeechResult(transcript: "Vorrei un capuccino per favore", alternatives: [], confidence: nil))
        #expect(m.isDone && m.passed == true)
        #expect(sink.drafts.map(\.outcome) == [.wrong, .correct])
        #expect(sink.drafts.allSatisfy { $0.mode == .spoken })
        let listenOnly = try #require(
            RepeatModel(payload: try PayloadFixtures.exercise("u02.l1.ex14"), env: env(), sink: sink))
        #expect(listenOnly.isListenOnly)
        listenOnly.skip()
        #expect(sink.drafts.count == 2)  // ungraded without speech: nothing recorded
    }
}
