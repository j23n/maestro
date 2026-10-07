import Foundation
import LearningCore
import Testing

@testable import Italiano

@MainActor
@Suite struct TaskExerciseModelTests {
    let sink = RecordingAttemptSink()

    func env(_ context: AttemptContext = .lesson, canSpeak: Bool = false) -> ExerciseEnvironment {
        var e = ExerciseEnvironment.preview(context: context)
        e.canSpeak = canSpeak
        return e
    }

    func conversation(_ context: AttemptContext = .lesson, canSpeak: Bool = false) throws -> ConversationModel {
        try #require(ConversationModel(payload: try PayloadFixtures.exercise("u02.l1.ex25"), env: env(context, canSpeak: canSpeak), sink: sink))
    }

    @Test func typedConversationTicksGoalsAndRecordsTurnsWithoutTargets() throws {
        let c = try conversation()
        #expect(c.lines.first?.text == "Buongiorno! Cosa prende?")
        c.response = "Vorrei un cappuccino e un cornetto, per favore."
        c.submitTyped()
        #expect(c.nodeID == "n3")
        #expect(c.goals.first { $0.id == "order" }?.done == true)
        c.response = "Arrivederci e grazie"
        c.submitTyped()
        #expect(c.isFinished)
        #expect(c.goalFraction == 1)
        #expect(sink.drafts.map(\.turnID) == ["n1", "n3"])
        #expect(sink.drafts.allSatisfy { $0.targets.isEmpty && $0.format == .conversation })
    }

    @Test func registerSlipGetsTheNearHintThenYouCouldSay() throws {
        let c = try conversation()
        c.response = "un cappuccino e un cornetto"
        c.submitTyped()
        c.response = "ecco grazie ciao"
        c.submitTyped()
        #expect(c.feedback == .hint("Giulia says Lei to you. Which goodbye goes with Lei?"))
        c.response = "boh"
        c.submitTyped()
        #expect(c.feedback == .youCouldSay("Ecco. Grazie, arrivederci!"))
        c.continueAfterMiss()
        #expect(c.isFinished)
        #expect(c.goals.first { $0.id == "bye" }?.done == false)
        #expect(sink.drafts.map(\.attemptIndex) == [1, 1, 2])
    }

    @Test func spokenTurnsUseTheTranscriptMatcher() throws {
        let c = try conversation(canSpeak: true)
        c.submitSpoken(SpeechResult(transcript: "buongiorno vorrei un capuccino e un cornetto", alternatives: [], confidence: nil))
        #expect(c.nodeID == "n3")
        #expect(sink.drafts.first?.mode == .spoken)
    }

    @Test func checkConversationsHideTypingAndGiveNoHints() throws {
        let c = try conversation(.check, canSpeak: true)
        #expect(!c.canType)
        c.submitSpoken(SpeechResult(transcript: "non lo so", alternatives: [], confidence: nil))
        #expect(c.feedback == nil)
        #expect(c.nodeID == "n3")  // moves on along the first intent
        #expect(c.goalFraction == 0)
    }

    @Test func talkFindsPoints() throws {
        let t = try #require(TalkModel(payload: try PayloadFixtures.exercise("u02.task.talk"), env: env(), sink: sink))
        #expect(t.canType)  // no speech on this device: typing is allowed in practice
        t.response = "Buonasera! Vorrei un caffè. Quanto costa?"
        t.submitTyped()
        #expect(t.found == ["greet", "price"])
        #expect(t.credit == 1)
        #expect(sink.drafts.last?.outcome == .correct)
    }

    @Test func formFieldsValidate() throws {
        let w = try #require(WritingModel(payload: try PayloadFixtures.exercise("u01.task.write"), env: env(), sink: sink))
        #expect(w.isForm && w.fieldValues.count == 2)
        w.fieldValues = ["Anna", ""]
        w.submit()
        #expect(w.fieldValid == [true, false])
        #expect(w.credit == 0.5)
    }

    @Test func relayPrices() throws {
        let r = try #require(RelayModel(payload: try PayloadFixtures.exercise("u02.task.relay"), env: env(), sink: sink))
        #expect(r.answerText == "€1.60")
        r.response = "1.50"
        r.check()
        #expect(!r.isDone)
        r.tryAgain()
        let reopened = if case .awaitingSecond = r.machine.state { true } else { false }
        #expect(reopened)
        r.response = "It's 1,60 euros"
        r.check()
        #expect(r.isDone)
        #expect(sink.drafts.map(\.outcome) == [.wrong, .correct])
    }
}
