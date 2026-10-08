import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Unit check scoring, § Placement, § Final A1 check.
@Suite struct CheckScoringTests {
    typealias C = TestCourse
    let content = TestCourse.standard
    var check: ContentIndex.Check { content.check(C.checkId(2))! }

    @Test func outcomesEarnFullHalfOrNothing() {
        #expect(CheckScoring.earned(score: 2, answer: .outcome(.correct)) == 2)
        #expect(CheckScoring.earned(score: 2, answer: .outcome(.correctWithNote)) == 2)
        #expect(CheckScoring.earned(score: 2, answer: .outcome(.almost)) == 1)
        for o in [AttemptOutcome.wrong, .revealed, .skipped] {
            #expect(CheckScoring.earned(score: 2, answer: .outcome(o)) == 0)
        }
        #expect(CheckScoring.earned(score: 1, answer: nil) == 0)
    }

    @Test func talkAndWritingEarnFoundOverRequiredCapped() {
        #expect(CheckScoring.earned(score: 2, answer: .points(found: 1, required: 2)) == 1)
        #expect(CheckScoring.earned(score: 2, answer: .points(found: 3, required: 2)) == 2)
        #expect(CheckScoring.earned(score: 3, answer: .points(found: 0, required: 2)) == 0)
        #expect(CheckScoring.isFullScore(.points(found: 2, required: 2)))
        #expect(!CheckScoring.isFullScore(.points(found: 1, required: 2)))
    }

    @Test func conversationEarnsGoalsCompletedOverGoals() {
        #expect(CheckScoring.earned(score: 2, answer: .goals(completed: 1, total: 2)) == 1)
        #expect(CheckScoring.earned(score: 3, answer: .goals(completed: 3, total: 3)) == 3)
        #expect(CheckScoring.earned(score: 3, answer: .goals(completed: 0, total: 3)) == 0)
    }

    func answers(_ pairs: [(Int, CheckAnswer)]) -> [ExerciseID: CheckAnswer] {
        Dictionary(uniqueKeysWithValues: pairs.map { (C.checkEx(2, $0.0), $0.1) })
    }

    /// Sections: listening 01, 02 · reading 03, 04 · writing 05, 06 · speaking 07 (2), 08 (2). Possible 10.
    @Test func sectionsOverallAndThePassRule() {
        let all = answers([(1, .outcome(.correct)), (2, .outcome(.almost)), (3, .outcome(.correct)),
                           (4, .outcome(.wrong)), (5, .outcome(.correct)), (6, .outcome(.correct)),
                           (7, .goals(completed: 1, total: 2)), (8, .points(found: 2, required: 2))])
        let r = CheckScoring.score(check: check, answers: all, content: content)
        #expect(r.sections.map(\.earned) == [1.5, 1, 2, 3])
        #expect(r.sections.map(\.possible) == [2, 2, 2, 4])
        #expect(r.overall == 7.5 / 10)
        #expect(r.passed)
        #expect(r.wrongTargets == [ItemSkillPair(C.storyWord(2), .read)])
        #expect(r.payload.kind == .unit)
        #expect(r.payload.checkId == C.checkId(2))
    }

    @Test func passNeedsSeventyPercentOverall() {
        // 7 of 10 passes exactly; 6.5 doesn't.
        let seven = answers([(1, .outcome(.correct)), (2, .outcome(.correct)), (3, .outcome(.correct)),
                             (5, .outcome(.correct)), (7, .goals(completed: 1, total: 2)),
                             (8, .points(found: 2, required: 2))])
        let r = CheckScoring.score(check: check, answers: seven, content: content)
        #expect(r.overall == 0.7)
        #expect(r.passed)
        var less = seven
        less[C.checkEx(2, 5)] = .outcome(.almost)
        #expect(!CheckScoring.score(check: check, answers: less, content: content).passed)
    }

    @Test func passNeedsHalfOfEverySection() {
        // 8 of 10 overall, but reading 0 of 2.
        let r = CheckScoring.score(
            check: check,
            answers: answers([(1, .outcome(.correct)), (2, .outcome(.correct)), (5, .outcome(.correct)),
                              (6, .outcome(.correct)), (7, .goals(completed: 2, total: 2)),
                              (8, .points(found: 2, required: 2))]),
            content: content)
        #expect(r.overall == 0.8)
        #expect(!r.passed)
        // Exactly half a section is enough.
        let half = CheckScoring.score(
            check: check,
            answers: answers([(1, .outcome(.correct)), (2, .outcome(.correct)), (3, .outcome(.correct)),
                              (5, .outcome(.correct)), (6, .outcome(.correct)), (7, .goals(completed: 2, total: 2)),
                              (8, .points(found: 2, required: 2))]),
            content: content)
        #expect(half.sections[1].fraction == 0.5)
        #expect(half.passed)
    }

    @Test func excludedSectionsAreFlaggedAndNotCounted() {
        // No speech: speaking is excluded; the rest scores 5 of 6.
        let r = CheckScoring.score(
            check: check,
            answers: answers([(1, .outcome(.correct)), (2, .outcome(.correct)), (3, .outcome(.correct)),
                              (4, .outcome(.wrong)), (5, .outcome(.correct)), (6, .outcome(.correct))]),
            excludedSections: ["speaking"], content: content)
        #expect(r.excludedSections == ["speaking"])
        #expect(r.sections.last?.excluded == true)
        #expect(r.overall == 5.0 / 6)
        #expect(r.passed)
        #expect(r.payload.sections.last?.excluded == true)
    }

    @Test func canDoReachedWithTwoThirdsOfItsTaggedItemsAtFullScore() {
        #expect((1...7).map { CheckScoring.requiredForCanDo(taggedCount: $0) } == [1, 2, 2, 3, 4, 4, 5])
        // cd:u02-a tags 01, 05, 06, 07 (n = 4, needs 3); cd:u02-b tags 03, 04, 07, 08 (needs 3).
        let r = CheckScoring.score(
            check: check,
            answers: answers([(1, .outcome(.correct)), (5, .outcome(.correctWithNote)), (6, .outcome(.almost)),
                              (7, .goals(completed: 2, total: 2)), (3, .outcome(.correct)),
                              (4, .outcome(.correct)), (8, .points(found: 1, required: 2))]),
            content: content)
        #expect(r.canDosReached == [C.canDo(2, "a"), C.canDo(2, "b")])
        let fewer = CheckScoring.score(
            check: check,
            answers: answers([(1, .outcome(.correct)), (5, .outcome(.almost)), (6, .outcome(.almost)),
                              (7, .goals(completed: 2, total: 2)), (3, .outcome(.correct))]),
            content: content)
        #expect(fewer.canDosReached.isEmpty)
        // Items in an excluded section don't count towards n.
        let noSpeech = CheckScoring.score(
            check: check, answers: answers([(1, .outcome(.correct)), (5, .outcome(.correct))]),
            excludedSections: ["speaking"], content: content)
        #expect(noSpeech.canDosReached == [C.canDo(2, "a")])
    }

    @Test func aFailedCheckMakesWrongItemsFocusAndRetakesKeepTheBest() throws {
        let d = TestDevice()
        let stepId = C.unitStep(2, "check")
        d.enter(stepId)
        let wrong: Set<Int> = [2, 6]
        var given: [ExerciseID: CheckAnswer] = [:]
        for n in 1...8 {
            let outcome: AttemptOutcome = wrong.contains(n) ? .wrong : n == 1 ? .almost : .correct
            d.answer(C.checkEx(2, n), outcome, context: .check, step: stepId,
                     turnId: n == 7 ? "n1" : nil)
            given[C.checkEx(2, n)] = n == 7 ? .goals(completed: 0, total: 2) : n == 8 ? .points(found: 0, required: 2)
                : .outcome(outcome)
        }
        let result = CheckScoring.score(check: check, answers: given, content: content)
        #expect(!result.passed)
        d.record(d.factory.checkCompleted(result.payload))
        #expect(Set(d.state.focusItems.keys) == Set(result.wrongTargets))
        #expect(Set(result.wrongTargets)
                == [ItemSkillPair(C.noun(2, 2), .listen), ItemSkillPair(C.noun(2, 3), .recall)])
        let first = try #require(d.state.units["u02"])
        #expect(first.checkScore == result.overall)
        #expect(first.checkPassed == false)
        #expect(d.state.unitState("u03") == .available)  // ADR-16
        // A retake the next day passes; a third scores lower.
        d.advance(day)
        d.record(d.factory.checkCompleted(CheckCompletedPayload(checkId: check.id, kind: .unit, sections: [],
                                                                overall: 0.9, passed: true, canDosReached: [])))
        d.record(d.factory.checkCompleted(CheckCompletedPayload(checkId: check.id, kind: .unit, sections: [],
                                                                overall: 0.75, passed: true, canDosReached: [])))
        #expect(d.state.units["u02"]?.checkScore == 0.9)
        #expect(d.state.units["u02"]?.checkPassed == true)
    }

    // MARK: Final check

    @Test func finalCheckScoresTwelvePointSectionsWithAnIndicativePass() throws {
        let final = try #require(content.finalCheck)
        var answers: [ExerciseID: CheckAnswer] = [:]
        // Each section has 3 items of 4 points: 2 right = 8/12, 1 right + 1 almost = 6/12.
        for section in final.sections {
            for (n, id) in section.exerciseIds.enumerated() {
                let weak = section.id == "writing"
                answers[id] = .outcome(n == 0 ? .correct : n == 1 ? (weak ? .almost : .correct) : .wrong)
            }
        }
        let r = CheckScoring.scoreFinal(final, answers: answers, content: content)
        #expect(r.sections.map(\.max) == [12, 12, 12, 12, 12])
        #expect(r.sections.map(\.points) == [8, 8, 8, 6, 8])
        #expect(r.sections.map(\.passed) == [true, true, true, false, true])
        #expect(!r.indicativePass)
        answers[final.sections[3].exerciseIds[1]] = .outcome(.correct)
        let better = CheckScoring.scoreFinal(final, answers: answers, content: content)
        #expect(better.indicativePass)
        #expect(better.payload.kind == .final)
        #expect(better.payload.sections.map(\.possible) == [12, 12, 12, 12, 12])
        #expect(better.payload.overall == 40.0 / 60)
        // 7/12 is the mark.
        let seven = CheckScoring.scoreFinal(
            ContentIndex.FinalAssessment(sections: [.init(id: "x", exerciseIds: (1...12).map { ExerciseID("x\($0)") },
                                                          max: 12)]),
            answers: Dictionary(uniqueKeysWithValues: (1...7).map {
                (ExerciseID("x\($0)"), CheckAnswer.outcome(.correct))
            }),
            content: content)
        #expect(seven.sections[0].points == 7)
        #expect(seven.indicativePass)
    }
}

@Suite struct PlacementTests {
    typealias C = TestCourse
    let content = TestCourse.standard
    var assessment: ContentIndex.PlacementAssessment { content.placement! }

    /// Runs the adaptive blocks, answering `correctPerBlock[unit]` items of each block right.
    func run(_ correctPerBlock: [Int]) -> [PlacementBlockResult] {
        var results: [PlacementBlockResult] = []
        while let block = Placement.nextBlock(after: results, assessment: assessment) {
            let right = correctPerBlock[results.count]
            var answers: [ExerciseID: AttemptOutcome] = [:]
            for (n, id) in block.exerciseIds.enumerated() { answers[id] = n < right ? .correct : .wrong }
            results.append(Placement.blockResult(block, answers: answers, content: content))
        }
        return results
    }

    @Test func startsAtTheFirstBlockBelowFour() throws {
        let results = run([5, 4, 3, 5, 5, 5, 5, 5])
        #expect(results.map(\.unit) == ["u01", "u02", "u03"])  // stops after the failed block
        #expect(results.map(\.correct) == [5, 4, 3])
        #expect(results.allSatisfy { $0.total == 5 })
        let completion = try #require(Placement.completion(results: results, assessment: assessment,
                                                           content: content))
        #expect(completion.startUnit == "u03")
        #expect(completion.completed.blocks == results)
        let introduced = try #require(completion.introduced)
        #expect(introduced.via == .placement)
        #expect(Set(introduced.items.map(\.itemId))
                == Set((0..<3).flatMap { content.items(in: C.unitId($0)).map(\.id) }))

        // Replayed: units 0–2 skipped, Unit 3 available, the catch-up queue filled.
        let d = TestDevice()
        d.record(d.factory.placementCompleted(completion.completed))
        d.record(completion.introduced.flatMap { d.factory.introduced($0) })
        #expect(d.state.unitState("u02") == .skipped)
        #expect(d.state.unitState("u03") == .available)
        #expect(d.state.memory.isEmpty)  // FSRS state comes from real reviews only
        #expect(Progression.continuePoint(state: d.state, content: content)?.unitId == "u03")
    }

    @Test func almostCountsHalfSoFourAndAHalfPassesButThreeAndAHalfDoesNot() throws {
        let block = assessment.blocks[0]
        var answers: [ExerciseID: AttemptOutcome] = [:]
        for (n, id) in block.exerciseIds.enumerated() { answers[id] = n < 3 ? .correct : .almost }
        let r = Placement.blockResult(block, answers: answers, content: content)
        #expect(r.correct == 4)
        #expect(Placement.passes(r, assessment: assessment))
        answers[block.exerciseIds[4]] = .wrong
        #expect(!Placement.passes(Placement.blockResult(block, answers: answers, content: content),
                                  assessment: assessment))
    }

    @Test func allBlocksPassingStartsAtUnitNine() throws {
        let results = run([5, 5, 4, 5, 4, 5, 5, 4])
        #expect(results.count == 8)
        #expect(Placement.nextBlock(after: results, assessment: assessment) == nil)
        let completion = try #require(Placement.completion(results: results, assessment: assessment,
                                                           content: content))
        #expect(completion.startUnit == "u09")
        #expect(Set(completion.introduced?.items.map(\.itemId) ?? [])
                == Set((0..<9).flatMap { content.items(in: C.unitId($0)).map(\.id) }))
    }

    @Test func failingTheFirstBlockStartsAtUnitOne() throws {
        let results = run([2])
        #expect(try #require(Placement.completion(results: results, assessment: assessment, content: content))
                    .startUnit == "u01")
        #expect(Placement.startUnit(results: [], assessment: assessment, content: content) == nil)
    }

    @Test func startFromTheBeginningWritesUnitZeroAndNoIntroductions() throws {
        let partial = run([5, 5, 2])
        let start = try #require(Placement.startFromBeginning(results: partial, content: content))
        #expect(start.startUnit == "u00")
        #expect(start.introduced == nil)
        #expect(start.completed.blocks == partial)
        let d = TestDevice()
        d.record(d.factory.placementCompleted(start.completed))
        #expect(d.state.unitState("u00") == .available)
        #expect(d.state.introductions.isEmpty)
    }
}

@Suite struct ProgressTests {
    typealias C = TestCourse
    let content = TestCourse.standard

    @Test func wordsKnownNeedTwoRepsAndHighRetrievability() {
        let d = TestDevice()
        let recall2 = C.ex(0, 2)  // noun 1 recall (scheduled)
        let read = C.ex(0, 10)  // story word read (scheduled for R)
        d.answer(recall2, .correct)
        #expect(Progress.wordsKnown(state: d.state, content: content, now: d.now) == 0)  // one rep
        d.advance(2 * day)
        d.answer(recall2, .correct)
        d.answer(read, .correct)
        d.advance(2 * day)
        d.answer(read, .correct)
        #expect(Progress.knownWords(state: d.state, content: content, now: d.now) == [C.noun(0, 1), C.storyWord(0)])
        // Long after, retrievability has dropped below 0.85.
        #expect(Progress.wordsKnown(state: d.state, content: content, now: d.now + 60 * day) == 0)
        // Grammar points never count as words.
        let g = TestDevice()
        g.answer(C.ex(0, 1), .correct)
        g.advance(2 * day)
        g.answer(C.ex(0, 12), .correct)
        #expect(Progress.wordsKnown(state: g.state, content: content, now: g.now) == 0)
    }

    @Test func skillBarsFollowRetrievability() throws {
        let d = TestDevice()
        let pair = ItemSkillPair(C.noun(0, 1), .recall)
        #expect(Progress.skillBars(pair, state: d.state, now: d.now) == 0)
        d.answer(C.ex(0, 2), .correct)
        let memory = try #require(d.state.memory[pair])
        let fsrs = FSRS6()
        func bars(afterDays days: Int64) -> Int {
            Progress.skillBars(pair, state: d.state, now: memory.lastReviewMs + days * day)
        }
        for days: Int64 in [0, 1, 3, 10, 40, 400] {
            let r = fsrs.retrievability(memory, atMs: memory.lastReviewMs + days * day)
            let expected = r < 0.5 ? 1 : r < 0.7 ? 2 : r < 0.9 ? 3 : 4
            #expect(bars(afterDays: days) == expected)
        }
        #expect(bars(afterDays: 0) == 4)
        #expect(bars(afterDays: 400) == 1)
        #expect(Progress.skillBars(item: C.noun(0, 1), state: d.state, now: d.now)[.read] == 0)
    }

    @Test func weeklyGoalCountsActiveDaysOfTheISOWeek() {
        // Sunday 2026-01-04 (previous week), then Monday, Tuesday and Thursday of the week of 5 January.
        let d = TestDevice(start: mondayNine - day)
        d.complete(C.step(0, "story"))
        d.advance(day)
        d.complete(C.step(0, "story"))  // Monday: a step
        d.advance(day)
        for n in 0..<5 { d.answer(C.ex(0, 2 + n % 4), .correct, context: .review, session: "r") }  // Tuesday: 5 cards
        d.advance(day)
        for n in 0..<4 { d.answer(C.ex(0, 2 + n % 4), .correct, context: .review, session: "r2") }  // Wednesday: 4
        d.advance(day)
        d.complete(C.step(0, "note"))  // Thursday
        let week = Progress.week(state: d.state, now: d.now, tzOffsetMinutes: 0, goal: 5)
        #expect(week.weekStart == LocalDay.dayNumber(ms: mondayNine, tzOffsetMinutes: 0))
        #expect(week.days == [true, true, false, true, false, false, false])
        #expect(week.activeDays == 3)
        #expect(!week.goalMet)
        // Next Monday starts a new week.
        #expect(Progress.week(state: d.state, now: mondayNine + 7 * day, tzOffsetMinutes: 0, goal: 5).activeDays == 0)
    }
}
