import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Replay: the derived resume cursor.
@Suite struct ResumeCursorTests {
    typealias C = TestCourse
    let practice = C.step(2, "practice")

    var step: ContentIndex.Step {
        get throws { try #require(TestCourse.standard.step(practice)) }
    }

    @Test func practiceOrderIsTheBlockThenTheSeededMix() throws {
        let s = try step
        #expect(s.presentationOrder == s.block + s.mix.seededShuffle(seed: "u02.l1.step-practice"))
        #expect(Array(s.presentationOrder.prefix(8)) == (1...8).map { C.ex(2, $0) })
        #expect(Set(s.presentationOrder.suffix(6)) == Set(s.mix))
        // Every device computes the same order: FNV-1a 64 of the step ID seeds SplitMix64.
        var rng = SplitMix64(seed: FNV1a64.hash("u02.l1.step-practice"))
        #expect(s.mix.seededShuffle(using: &rng) == Array(s.presentationOrder.suffix(6)))
    }

    @Test func quitMidStepAndResumeAtTheSameExercise() throws {
        let s = try step
        let d = TestDevice()
        for k in 0..<2 { d.runUnit(k) }
        for other in d.content.steps(in: C.unitId(2)) where other.ord < s.ord { d.run(other.id) }
        d.enter(practice)
        let order = s.presentationOrder
        for id in order.prefix(8) { d.answer(id, .correct, step: practice) }
        d.answer(order[8], .almost, step: practice)  // final
        d.answer(order[9], .wrong, step: practice)  // first try wrong: not final yet
        #expect(d.state.cursor(practice) == 9)
        // The app quits here. On relaunch, Continue leads back to this step and exercise.
        let relaunched = Replay.rebuildAll(events: d.events, content: d.content)
        #expect(relaunched == d.state)
        let point = try #require(Progression.continuePoint(state: relaunched, content: d.content))
        #expect(point.stepId == practice)
        #expect(point.cursor == 9)
        #expect(Progression.resumeExercise(step: s, state: relaunched) == order[9])
        // Reopening a half-done step writes no stepStarted.
        #expect(!Progression.shouldWriteStepStarted(practice, state: relaunched))
        let before = d.events.count
        d.enter(practice)
        #expect(d.events.count == before)
        d.answer(order[9], .correct, step: practice, attemptIndex: 2)  // second attempts are final
        #expect(d.state.cursor(practice) == 10)
        for id in order.suffix(order.count - 10) { d.answer(id, .wrong, step: practice, attemptIndex: 2) }
        #expect(d.state.cursor(practice) == order.count)
        #expect(Progression.resumeExercise(step: s, state: d.state) == nil)
        d.complete(practice)
        #expect(d.state.cursor(practice) == 0)
        #expect(d.state.isStepComplete(practice))
        #expect(Progression.shouldWriteStepStarted(practice, state: d.state))
    }

    @Test func theCursorIsTheAnsweredPrefix() throws {
        let s = try step
        let d = TestDevice()
        d.enter(practice)
        d.answer(s.presentationOrder[0], .correct, step: practice)
        d.answer(s.presentationOrder[2], .correct, step: practice)
        #expect(d.state.cursor(practice) == 1)
        d.answer(s.presentationOrder[1], .revealed, step: practice)
        #expect(d.state.cursor(practice) == 3)
    }

    @Test func aRevisitCountsFromItsOwnStart() throws {
        let s = try step
        let d = TestDevice()
        d.run(practice)
        d.enter(practice)  // a revisit: a new stepStarted
        #expect(d.state.cursor(practice) == 0)
        d.answer(s.presentationOrder[0], .correct, step: practice)
        #expect(d.state.cursor(practice) == 1)
        // Another device that didn't know about the open start writes its own: the last start is the open one.
        d.record(TestDevice("tablet", start: d.now).factory.stepStarted(practice, sessionId: "other"))
        #expect(d.state.cursor(practice) == 0)
        #expect(d.state.stepProgress(practice)?.startedAt == mondayNine)
    }

    @Test func attemptsWithoutAnOpenStartDoNotMoveTheCursor() throws {
        let s = try step
        let d = TestDevice()
        d.answer(s.presentationOrder[0], .correct, step: practice)
        #expect(d.state.stepProgress(practice) == nil)
        #expect(d.state.cursor(practice) == 0)
    }

    @Test func checkAnswersAreFinalAndConversationTurnsAreNot() throws {
        let d = TestDevice()
        let checkStep = C.unitStep(0, "check")
        let check = try #require(d.content.step(checkStep))
        d.enter(checkStep)
        // One attempt per item in a check: a wrong answer is final.
        d.answer(check.presentationOrder[0], .wrong, context: .check, step: checkStep)
        #expect(d.state.cursor(checkStep) == 1)
        for id in check.presentationOrder[1..<6] { d.answer(id, .correct, context: .check, step: checkStep) }
        #expect(d.state.cursor(checkStep) == 6)
        // The conversation (index 6): turns never finish it, so resuming restarts the dialogue.
        d.answer(check.presentationOrder[6], .correct, context: .check, step: checkStep, turnId: "n1")
        #expect(d.state.cursor(checkStep) == 6)
    }
}
