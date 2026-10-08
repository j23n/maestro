import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Placement, docs/06 §19: one sitting of the adaptive blocks, and what follows it (skipped units, the
/// catch-up queue); docs/05 § Final A1 check: when the final check can be taken.
@Suite struct PlacementSessionTests {
    typealias C = TestCourse
    let content = TestCourse.standard

    /// Plays a sitting like the app: one attempt per item (a second one is ignored), then Continue. `right[b]` is how
    /// many of block b's items the learner gets right.
    func sit(_ right: [Int], session start: PlacementSession? = nil) throws -> PlacementSession {
        var session = try #require(start ?? PlacementSession(assessment: content.placement, content: content))
        while let id = session.currentExercise {
            let n = session.position
            let outcome: AttemptOutcome = n < right[session.results.count] ? .correct : .wrong
            session.record(outcome, for: id)
            session.record(.correct, for: id)  // a second attempt never counts
            session.advance(content: content)
        }
        return session
    }

    @Test func aScriptedLearnerIsPlacedAtUnitThreeAndGetsCatchUpCards() throws {
        let session = try sit([5, 4, 2, 5, 5, 5, 5, 5])
        #expect(session.isFinished && session.progress == 1)
        #expect(session.results.map(\.unit) == ["u01", "u02", "u03"])
        #expect(session.results.map(\.correct) == [5, 4, 2])
        #expect(session.answeredCount == 15 && session.maximumCount == 40)
        #expect(session.startUnit(content: content) == "u03")
        let completion = try #require(session.completion(content: content))
        #expect(completion.startUnit == "u03")

        // The app writes the attempts (context placement), then placementCompleted and the introductions.
        let d = TestDevice()
        for (id, outcome) in session.answers.sorted(by: { $0.key < $1.key }) {
            d.answer(id, outcome, context: .placement, session: "s-placement")
        }
        d.record(d.factory.placementCompleted(completion.completed))
        d.record(completion.introduced.flatMap { d.factory.introduced($0) })
        #expect((0..<3).allSatisfy { d.state.unitState(C.unitId($0)) == .skipped })
        #expect(d.state.unitState("u03") == .available)
        #expect(d.state.memory.isEmpty)  // placement never invents memory
        #expect(Progression.continuePoint(state: d.state, content: content)?.unitId == "u03")

        // Today: the skipped units' scheduled pairs wait in the catch-up queue, 15 a day, in course order.
        let skipped = Set((0..<3).flatMap { content.items(in: C.unitId($0)).map(\.id) })
        let queued = content.scheduledPairs.filter { skipped.contains($0.itemId) }
        let plan = Planner(content: content, state: d.state).today(now: d.now, tzOffsetMinutes: d.tz)
        #expect(plan.catchUp.waiting == queued.count && queued.count > 15)
        #expect(plan.catchUp.count == 15)
        #expect(plan.review.dueCount == 0)
        let builder = Planner(content: content, state: d.state).sessionBuilder
        let catchUp = builder.buildCatchUp(sessionId: "s-catchup", now: d.now, tzOffsetMinutes: d.tz)
        #expect(catchUp.kind == .catchUp && catchUp.cards.count == 15)
        #expect(catchUp.cards.allSatisfy { $0.source == .catchUp && skipped.contains($0.pair.itemId) })
        #expect(catchUp.cards.allSatisfy { d.state.introductions[$0.pair]?.via == .placement })
        // Course order: Unit 0's pairs come first.
        #expect(catchUp.cards.contains { content.item($0.pair.itemId)?.unitId == "u00" })

        // Reviewing them builds real FSRS memory and uses up the day's allowance; tomorrow brings 15 more.
        for card in catchUp.cards {
            d.answer(
                card.exerciseId, .correct, context: .review, session: "s-catchup", format: card.format,
                targets: [card.pair])
        }
        #expect(d.state.memory.count == 15)
        let after = Planner(content: content, state: d.state).today(now: d.now, tzOffsetMinutes: d.tz)
        #expect(after.catchUp.count == 0 && after.catchUp.waiting == queued.count - 15)
        d.advance(day)
        let tomorrow = Planner(content: content, state: d.state).today(now: d.now, tzOffsetMinutes: d.tz)
        #expect(tomorrow.catchUp.count == min(15, queued.count - 15) && tomorrow.catchUp.count > 0)
    }

    @Test func progressCountsEveryItemPlacementCanAsk() throws {
        var session = try #require(PlacementSession(assessment: content.placement, content: content))
        #expect(session.maximumCount == 40 && session.progress == 0)
        #expect(session.currentBlock?.unitId == "u01" && session.currentExercise == "pl.u01.1")
        for _ in 0..<6 { session.advance(content: content) }  // passed over: unanswered earns nothing
        #expect(session.results.map(\.correct) == [0])
        #expect(session.isFinished && session.startUnit(content: content) == "u01")
        #expect(session.progress == 1)
    }

    @Test func oneAttemptPerItemAndOnlyForTheItemOnScreen() throws {
        var session = try #require(PlacementSession(assessment: content.placement, content: content))
        session.record(.correct, for: "pl.u01.2")  // not on screen
        session.record(.almost, for: "pl.u01.1")
        session.record(.correct, for: "pl.u01.1")
        #expect(session.answers == ["pl.u01.1": .almost])
        session.advance(content: content)
        #expect(session.currentExercise == "pl.u01.2" && session.answeredCount == 1)
        #expect(session.progress == 1.0 / 40)
    }

    @Test func startFromTheBeginningAtAnyPoint() throws {
        var session = try #require(PlacementSession(assessment: content.placement, content: content))
        for id in content.placement?.blocks[0].exerciseIds ?? [] {
            session.record(.correct, for: id)
            session.advance(content: content)
        }
        session.record(.correct, for: "pl.u02.1")
        session.advance(content: content)
        #expect(session.completion(content: content) == nil)  // blocks remain
        let start = try #require(session.startFromBeginning(content: content))
        #expect(start.startUnit == "u00" && start.introduced == nil)
        #expect(start.completed.blocks.map(\.unit) == ["u01"])
    }

    /// A content index like the standard course but with other placement blocks.
    func content(placement: ContentIndex.PlacementAssessment?) -> ContentIndex {
        let c = content
        return ContentIndex(
            packVersion: c.packVersion, contentHash: c.contentHash, units: c.units, lessons: c.lessons,
            steps: c.steps, items: c.items, exercises: c.exercises, texts: c.texts, notes: c.notes,
            canDos: c.canDos, checks: c.checks, placement: placement, finalCheck: c.finalCheck, sounds: c.sounds)
    }

    @Test func aPartialPackPlacesAtTheFirstUnitWithoutQuestions() throws {
        let full = try #require(content.placement)
        // Blocks 4–8 aren't written yet; block 6 names an exercise the pack lacks.
        var blocks = full.blocks.enumerated().map { n, b in
            n < 3 ? b : .init(unitId: b.unitId, exerciseIds: [])
        }
        blocks[5] = .init(unitId: blocks[5].unitId, exerciseIds: ["pl.missing"])
        let partial = content(placement: .init(advanceThreshold: 4, blocks: blocks))
        #expect(PlacementSession.runnableBlocks(.init(blocks: blocks), content: partial).count == 3)
        var session = try #require(PlacementSession(assessment: partial.placement, content: partial))
        #expect(session.maximumCount == 15)
        while let id = session.currentExercise {
            session.record(.correct, for: id)
            session.advance(content: partial)
        }
        #expect(session.results.count == 3)
        #expect(session.completion(content: partial)?.startUnit == "u04")

        // No runnable block, no placement.
        let skeleton = full.blocks.map { ContentIndex.PlacementAssessment.Block(unitId: $0.unitId, exerciseIds: []) }
        let empty = content(placement: .init(blocks: skeleton))
        #expect(PlacementSession(assessment: empty.placement, content: empty) == nil)
        #expect(PlacementSession(assessment: nil, content: content) == nil)
    }
}

@Suite struct FinalCheckAvailabilityTests {
    typealias C = TestCourse
    let content = TestCourse.standard

    @Test func availableOnceUnitTwelveIsCompleted() throws {
        let d = TestDevice()
        #expect(!FinalCheck.isAvailable(state: d.state, content: content))
        d.record(
            d.factory.checkCompleted(
                CheckCompletedPayload(
                    checkId: C.checkId(11), kind: .unit, sections: [], overall: 0.8, passed: true, canDosReached: [])))
        #expect(!FinalCheck.isAvailable(state: d.state, content: content))
        d.record(
            d.factory.checkCompleted(
                CheckCompletedPayload(
                    checkId: C.checkId(12), kind: .unit, sections: [], overall: 0.8, passed: true, canDosReached: [])))
        #expect(FinalCheck.isAvailable(state: d.state, content: content))
        // Without a final review unit, Unit 12's completion is enough.
        let noFinal = TestCourse.make(withFinal: false)
        let e = TestDevice(content: noFinal)
        e.record(
            e.factory.checkCompleted(
                CheckCompletedPayload(
                    checkId: C.checkId(12), kind: .unit, sections: [], overall: 0.8, passed: true, canDosReached: [])))
        #expect(FinalCheck.isAvailable(state: e.state, content: noFinal))
    }

    @Test func runnableOnlyWithEverySectionWritten() throws {
        let final = try #require(content.finalCheck)
        #expect(FinalCheck.isRunnable(final, content: content))
        #expect(!FinalCheck.isRunnable(nil, content: content))
        var sections = final.sections
        sections[2].exerciseIds = []
        #expect(!FinalCheck.isRunnable(ContentIndex.FinalAssessment(sections: sections), content: content))
        sections[2].exerciseIds = ["fin.missing"]
        #expect(!FinalCheck.isRunnable(ContentIndex.FinalAssessment(sections: sections), content: content))
    }

    @Test func itemsTheLearnerNeverMetAreMissingBeforeTheCheck() throws {
        let met = ItemSkillPair(C.noun(0, 1), .recall)
        let unmet = ItemSkillPair(C.noun(12, 2), .recall)
        let spoken = ItemSkillPair(C.noun(12, 3), .speak)
        let withRequires = ContentIndex(
            units: content.units, items: content.items,
            exercises: [
                .init(id: "fin.r1", format: .recall, unitId: "u99", role: .final, requires: [met, unmet]),
                .init(id: "fin.s1", format: .talk, unitId: "u99", role: .final, requires: [spoken]),
            ],
            finalCheck: .init(sections: [
                .init(id: "structures", exerciseIds: ["fin.r1"], max: 12),
                .init(id: "speaking", exerciseIds: ["fin.s1"], max: 12),
            ]))
        let final = try #require(withRequires.finalCheck)
        let d = TestDevice(content: withRequires)
        d.record(d.factory.introduced([met], via: .preview))
        #expect(
            FinalCheck.missingRequirements(final, state: d.state, content: withRequires) == [unmet, spoken].sorted())
        // A section left out of the sitting asks for nothing.
        #expect(
            FinalCheck.missingRequirements(final, excluded: ["speaking"], state: d.state, content: withRequires)
                == [unmet])
        d.record(d.factory.introduced([unmet, spoken], via: .catchup))
        #expect(FinalCheck.missingRequirements(final, state: d.state, content: withRequires).isEmpty)
    }

    @Test func speechOnlySectionsAreTheOnesWithoutAnyTypedItem() throws {
        let final = try #require(content.finalCheck)
        #expect(FinalCheck.speechOnlySections(final, content: content).isEmpty)  // all choice in the test course
        let talkId = ExerciseID("fin.speaking.talk")
        let withTalk = ContentIndex(
            units: content.units,
            exercises: content.exercises + [.init(id: talkId, format: .talk, unitId: "u99", role: .final)],
            finalCheck: .init(sections: [
                .init(id: "reading", exerciseIds: ["fin.reading.01"], max: 12),
                .init(id: "speaking", exerciseIds: [talkId], max: 12),
            ]))
        let f = try #require(withTalk.finalCheck)
        #expect(FinalCheck.speechOnlySections(f, content: withTalk) == ["speaking"])
    }
}
