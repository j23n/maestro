import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Replay: the reducer, rebuilds, the incremental path and the rating policy in context.
@Suite struct ReplayTests {
    let content = TestCourse.standard
    typealias C = TestCourse

    /// A learner's first three days: Unit 0 with mixed answers, a failed then passed check, a review session.
    static func scriptedLog() -> [Event] {
        let d = TestDevice()
        for step in d.content.steps(in: C.unitId(0)) where step.kind != .check && step.kind != .fluency {
            d.enter(step.id)
            for (n, id) in step.presentationOrder.enumerated() {
                if n % 3 == 1 {
                    d.answer(id, .wrong, step: step.id)
                    d.answer(id, .correct, step: step.id, attemptIndex: 2)
                } else {
                    d.answer(id, n % 4 == 2 ? .almost : .correct, step: step.id)
                }
            }
            d.complete(step.id)
        }
        d.record(d.factory.session(sessionId: "s-lesson", kind: .lesson, platform: .iPhone, startedAt: mondayNine,
                                   endedAt: d.now, activeSeconds: 1_500))
        d.completeCheck(0, passed: false, overall: 0.4)
        d.advance(day)
        d.completeCheck(0, passed: true, overall: 0.9)
        d.advance(day)
        let reviewed = [C.ex(0, 2), C.ex(0, 3), C.ex(0, 4), C.ex(0, 5), C.ex(0, 10), C.ex(0, 13), C.ex(0, 20)]
        for (n, id) in reviewed.enumerated() {
            d.answer(id, n % 3 == 0 ? .wrong : .correct, context: .review, session: "review-1")
        }
        d.record(d.factory.session(sessionId: "review-1", kind: .review, platform: .iPhone, startedAt: d.now - 60_000,
                                   endedAt: d.now, activeSeconds: 240))
        return d.events
    }

    static let log = scriptedLog()

    @Test func theScriptedLogExercisesEveryPart() throws {
        let state = Replay.rebuildAll(events: Self.log, content: content)
        #expect(Self.log.count > 80, "\(Self.log.count) events")
        #expect(state.memory.count > 10)
        #expect(state.introductions.count > 20)
        #expect(state.unitState(C.unitId(0)) == .completed)
        #expect(state.unitState(C.unitId(1)) == .available)
        #expect(state.unitState(C.unitId(2)) == .locked)
        #expect(!state.focusItems.isEmpty)
        #expect(state.dailyActivity.count == 3)
        #expect(state.secondsPerCardSamples.count == 1)
    }

    @Test func rebuildIsIdempotentAndIgnoresDuplicates() throws {
        let once = Replay.rebuildAll(events: Self.log, content: content)
        let twice = Replay.rebuildAll(events: Self.log + Self.log.reversed(), content: content)
        #expect(once == twice)
        #expect(try once.canonicalEncoding() == twice.canonicalEncoding())
        #expect(try Replay.rebuildAll(events: Self.log, content: content).canonicalEncoding()
                == once.canonicalEncoding())
    }

    @Test(arguments: 0..<20)
    func arrivalOrderDoesNotMatter(seed: Int) throws {
        let reference = try Replay.rebuildAll(events: Self.log, content: content).canonicalEncoding()
        let shuffled = Self.log.seededShuffle(seed: "order-\(seed)")
        #expect(try Replay.rebuildAll(events: shuffled, content: content).canonicalEncoding() == reference)
    }

    @Test(arguments: 0..<20)
    func incrementalEqualsFullRebuild(seed: Int) throws {
        let reference = Replay.rebuildAll(events: Self.log, content: content)
        var rng = SplitMix64(seedString: "batches-\(seed)")
        var pending = Self.log.seededShuffle(using: &rng)
        var applied: [Event] = []
        var state = Replay.initialState(content: content)
        var rebuilds = 0
        while !pending.isEmpty {
            let size = 1 + rng.nextInt(below: min(25, pending.count))
            let batch = Array(pending.prefix(size))
            pending.removeFirst(size)
            applied += batch
            switch Replay.applyIncremental(state, events: batch, content: content) {
            case .applied(let next): state = next
            case .needsRebuild:
                rebuilds += 1
                state = Replay.rebuildAll(events: applied, content: content)
            }
            #expect(state == Replay.rebuildAll(events: applied, content: content))
        }
        #expect(try state.canonicalEncoding() == reference.canonicalEncoding())
        #expect(rebuilds > 0)
    }

    @Test func inOrderBatchesNeverNeedARebuild() {
        let ordered = Replay.ordered(Self.log)
        var state = Replay.initialState(content: content)
        for start in stride(from: 0, to: ordered.count, by: 7) {
            guard case .applied(let next) = Replay.applyIncremental(
                state, events: Array(ordered[start..<min(start + 7, ordered.count)]), content: content)
            else {
                Issue.record("unexpected rebuild")
                return
            }
            state = next
        }
        #expect(state == Replay.rebuildAll(events: Self.log, content: content))
        // Re-delivering the last event is a no-op; an earlier one asks for a rebuild.
        #expect(Replay.applyIncremental(state, events: [ordered[ordered.count - 1]], content: content)
                == .applied(state))
        #expect(Replay.applyIncremental(state, events: [ordered[0]], content: content) == .needsRebuild)
    }

    @Test func pureApplyMatchesInPlaceReduce() {
        var inPlace = Replay.initialState(content: content)
        var pure = Replay.initialState(content: content)
        for event in Replay.ordered(Self.log) {
            Replay.reduce(&inPlace, event, content: content)
            let before = pure
            pure = Replay.apply(pure, event, content: content)
            _ = before  // the input of `apply` is never modified
        }
        #expect(inPlace == pure)
    }

    @Test func canonicalEncodingRoundTrips() throws {
        let state = Replay.rebuildAll(events: Self.log, content: content)
        let data = try state.canonicalEncoding()
        let decoded = try JSONDecoder().decode(LearnerState.self, from: data)
        #expect(decoded == state)
        #expect(try decoded.canonicalEncoding() == data)
    }

    @Test func rebuildTriggers() {
        #expect(Replay.rebuildReason(storedDerivedVersion: nil, storedContentHash: nil, content: content)
                == .noDerivedState)
        #expect(Replay.rebuildReason(storedDerivedVersion: Replay.derivedVersion - 1, storedContentHash: "hash-1",
                                     content: content) == .derivedVersionChanged)
        #expect(Replay.rebuildReason(storedDerivedVersion: Replay.derivedVersion, storedContentHash: "old",
                                     content: content) == .contentChanged)
        #expect(Replay.rebuildReason(storedDerivedVersion: Replay.derivedVersion, storedContentHash: "hash-1",
                                     content: content) == nil)
    }

    // MARK: Rating policy in context

    func memory(after outcomes: [(AttemptOutcome, Int, AnswerMode)], exercise: ExerciseID,
                pair: ItemSkillPair) -> MemoryState?
    {
        let d = TestDevice()
        for (outcome, index, mode) in outcomes { d.answer(exercise, outcome, attemptIndex: index, mode: mode) }
        return d.state.memory[pair]
    }

    @Test func spokenFailSkippedAndSecondAttemptsMakeNoUpdate() {
        let repeatEx = C.ex(0, 8)  // repeat → c:u00-c1 speak
        let speak = ItemSkillPair(C.chunk(0), .speak)
        #expect(memory(after: [(.wrong, 1, .spoken)], exercise: repeatEx, pair: speak) == nil)
        #expect(memory(after: [(.skipped, 1, .spoken)], exercise: repeatEx, pair: speak) == nil)
        #expect(memory(after: [(.correct, 1, .spoken)], exercise: repeatEx, pair: speak)?.reps == 1)

        let recallEx = C.ex(0, 2)  // recall → noun 1 recall
        let recall = ItemSkillPair(C.noun(0, 1), .recall)
        #expect(memory(after: [(.skipped, 1, .typed)], exercise: recallEx, pair: recall) == nil)
        #expect(memory(after: [(.correct, 2, .typed)], exercise: recallEx, pair: recall) == nil)
        let wrongThenRight = memory(after: [(.wrong, 1, .typed), (.correct, 2, .typed)], exercise: recallEx,
                                    pair: recall)
        #expect(wrongThenRight?.reps == 1)
        #expect(wrongThenRight?.stability == FSRS6().initialStability(.again))
        #expect(memory(after: [(.almost, 1, .typed)], exercise: recallEx, pair: recall)?.difficulty
                == FSRS6().initialDifficulty(.hard))
        // A recall answered by voice and failed is logged only, under speak (ADR-08).
        #expect(memory(after: [(.wrong, 1, .spoken)], exercise: recallEx, pair: recall) == nil)
        #expect(memory(after: [(.wrong, 1, .spoken)], exercise: recallEx,
                       pair: ItemSkillPair(C.noun(0, 1), .speak)) == nil)
    }

    @Test func matchGivesEachPairItsOwnOutcome() {
        let d = TestDevice()
        d.answer(C.ex(0, 13), .wrong, pairOutcomes: [.correct, .wrong])
        #expect(d.state.memory[ItemSkillPair(C.noun(0, 1), .read)]?.stability == FSRS6().initialStability(.good))
        #expect(d.state.memory[ItemSkillPair(C.noun(0, 2), .read)]?.stability == FSRS6().initialStability(.again))
    }

    @Test func taskFormatsAndPlacementNeverUpdate() {
        let d = TestDevice()
        d.answer(C.checkEx(0, 7), .correct, context: .check, turnId: "n1",
                 targets: [ItemSkillPair(C.chunk(0), .recall)])
        d.answer(ExerciseID("pl.u01.1"), .correct, context: .placement)
        #expect(d.state.memory.isEmpty)
        d.answer(C.checkEx(0, 6), .correct, context: .check)
        #expect(d.state.memory[ItemSkillPair(C.noun(0, 3), .recall)]?.reps == 1)
    }

    // MARK: Missing IDs, unknown types

    @Test func retiredContentStillCountsForMemoryWhenTheItemExists() {
        let logger = RecordingLogger()
        let d = TestDevice()
        let retired = d.factory.attempt(exerciseId: "u00.l1.ex99", format: .recall, context: .lesson,
                                        stepId: "u00.l1.step-gone", sessionId: "s", outcome: .correct,
                                        targets: [ItemSkillPair(C.noun(0, 1), .recall),
                                                  ItemSkillPair("w:gone", .recall)],
                                        mode: .typed, latencyMs: 1)
        let unknown = d.factory.attempt(exerciseId: "u00.l1.ex98", format: .recall, context: .lesson, sessionId: "s",
                                        outcome: .correct, targets: [ItemSkillPair("w:gone", .recall)], mode: .typed,
                                        latencyMs: 1)
        let weird = d.factory.make(.unknown(type: "futureThing", json: Data("{}".utf8)))
        let intro = d.factory.introduced([ItemSkillPair("w:gone", .read), ItemSkillPair(C.noun(0, 4), .read)],
                                         via: .debug)
        let step = d.factory.stepStarted("u00.l1.step-gone", sessionId: "s")
        let state = Replay.rebuildAll(events: [retired, unknown, weird, step] + [intro].compactMap { $0 },
                                      content: content, logger: logger)
        #expect(state.memory[ItemSkillPair(C.noun(0, 1), .recall)]?.reps == 1)
        #expect(state.memory[ItemSkillPair("w:gone", .recall)] == nil)
        #expect(state.exerciseHistory["u00.l1.ex99"] != nil)
        #expect(state.exerciseHistory["u00.l1.ex98"] == nil)
        #expect(state.isIntroduced(ItemSkillPair(C.noun(0, 4), .read)))
        #expect(!state.isIntroduced(ItemSkillPair("w:gone", .read)))
        #expect(state.steps.isEmpty)
        #expect(state.lastApplied == Replay.ordered([retired, unknown, weird, step]).last?.key)
        #expect(logger.lines.count == 5)
        #expect(logger.lines.contains { $0.contains("unknown type 'futureThing'") })
    }

    @Test func theFirstIntroductionWins() {
        let d = TestDevice()
        let pair = ItemSkillPair(C.noun(0, 1), .read)
        d.record(d.factory.introduced([pair], via: .catchup))
        d.record(d.factory.introduced([pair], via: .preview))
        #expect(d.state.introductions[pair]?.via == .catchup)
        #expect(d.state.introductions[pair]?.at == mondayNine)
    }

    // MARK: Units, checks, can-dos, focus items

    @Test func unitsUnlockInOrderAndCompleteWithTheirCheck() {
        let d = TestDevice()
        #expect(d.state.unitState(C.unitId(0)) == .available)
        #expect(d.state.unitState(C.unitId(1)) == .locked)
        d.enter(C.unitStep(0, "opener"))
        #expect(d.state.unitState(C.unitId(0)) == .inProgress)
        d.completeCheck(0, passed: false, overall: 0.3)
        // ADR-16: any completed check unlocks the next unit.
        #expect(d.state.unitState(C.unitId(0)) == .completed)
        #expect(d.state.unitState(C.unitId(1)) == .available)
        #expect(d.state.units[C.unitId(0)]?.checkPassed == false)
        d.completeCheck(0, passed: true, overall: 0.8)
        d.completeCheck(0, passed: false, overall: 0.6)
        let unit = d.state.units[C.unitId(0)]
        #expect(unit?.checkScore == 0.8)  // the best score
        #expect(unit?.checkPassed == true)  // once any attempt passed
        #expect(unit?.completedAt == d.events.first { $0.type == "checkCompleted" }?.at)  // the first completion
    }

    @Test func canDosAreTheUnionOverAttempts() {
        let d = TestDevice()
        d.completeCheck(0, passed: true, canDos: [C.canDo(0, "a")])
        let firstAt = d.state.canDos[C.canDo(0, "a")]
        d.completeCheck(0, passed: true, canDos: [C.canDo(0, "b"), C.canDo(0, "a")])
        #expect(d.state.canDos[C.canDo(0, "a")] == firstAt)
        #expect(d.state.canDos[C.canDo(0, "b")] != nil)
        #expect(d.state.canDos.count == 2)
    }

    @Test func aFailedCheckMakesWrongTargetsFocusItemsForThreeDays() {
        let d = TestDevice()
        let stepId = C.unitStep(0, "check")
        d.enter(stepId)
        d.answer(C.checkEx(0, 1), .correct, context: .check, step: stepId)
        d.answer(C.checkEx(0, 2), .wrong, context: .check, step: stepId)
        d.answer(C.checkEx(0, 4), .almost, context: .check, step: stepId)
        d.answer(C.checkEx(0, 5), .skipped, context: .check, step: stepId)
        d.answer(C.checkEx(0, 6), .revealed, context: .check, step: stepId)
        let at = d.now
        d.record(d.factory.checkCompleted(CheckCompletedPayload(checkId: C.checkId(0), kind: .unit, sections: [],
                                                                overall: 0.3, passed: false, canDosReached: [])))
        let focus = d.state.focusItems
        #expect(Set(focus.keys) == [ItemSkillPair(C.noun(0, 2), .listen), ItemSkillPair(C.grammarP(0), .recall),
                                    ItemSkillPair(C.noun(0, 3), .recall)])
        #expect(focus.values.allSatisfy { $0.until == at + 3 * day && $0.reason == "check:u00.check" })
        #expect(d.state.activeFocus(now: at + 3 * day - 1).count == 3)
        #expect(d.state.activeFocus(now: at + 3 * day).isEmpty)
        // A passed check adds none.
        let passed = TestDevice()
        passed.completeCheck(0, passed: true)
        #expect(passed.state.focusItems.isEmpty)
    }

    @Test func checksOfUnknownUnitsAreSkipped() {
        let logger = RecordingLogger()
        let d = TestDevice()
        let e = d.factory.checkCompleted(CheckCompletedPayload(checkId: "u77.check", kind: .unit, sections: [],
                                                               overall: 1, passed: true, canDosReached: ["cd:x"]))
        let state = Replay.rebuildAll(events: [e], content: content, logger: logger)
        #expect(state.unitState(C.unitId(0)) == .available)
        #expect(state.canDos.isEmpty)
        #expect(logger.lines.count == 1)
    }

    @Test func theFinalCheckCompletesTheFinalReviewUnit() {
        let d = TestDevice()
        for k in 0..<13 { d.completeCheck(k, passed: true) }
        #expect(d.state.unitState("u99") == .available)
        d.record(d.factory.checkCompleted(CheckCompletedPayload(checkId: "final", kind: .final, sections: [],
                                                                overall: 0.5, passed: false, canDosReached: [])))
        d.record(d.factory.checkCompleted(CheckCompletedPayload(checkId: "final", kind: .final, sections: [],
                                                                overall: 0.7, passed: true, canDosReached: [])))
        #expect(d.state.unitState("u99") == .completed)
        #expect(d.state.finalCheck?.bestScore == 0.7)
        #expect(d.state.finalCheck?.passed == true)
        #expect(d.state.finalCheck?.attempts == 2)
        #expect(Progression.unitsCompleted(state: d.state, content: content) == 13)
    }

    // MARK: Daily activity

    @Test func dailyActivityRollsOverAtFourInTheEventsOwnOffset() {
        // 2026-01-06 02:30 UTC is still the 5th locally in UTC, but already 04:30 on the 6th in UTC+2.
        let early: Int64 = mondayNine + 17 * hour + 30 * minute
        let utc = TestDevice("utc", start: early, tz: 0)
        utc.complete(C.step(0, "story"))
        let plusTwo = TestDevice("plus-two", start: early, tz: 120)
        plusTwo.complete(C.step(0, "story"))
        #expect(utc.state.dailyActivity.values.map(\.localDay) == ["2026-01-05"])
        #expect(plusTwo.state.dailyActivity.values.map(\.localDay) == ["2026-01-06"])
    }

    @Test func dailyActivityCountsStepsCardsAndActiveSeconds() {
        let d = TestDevice()
        d.complete(C.step(0, "story"))
        d.complete(C.step(0, "story"))  // revisits count again
        for n in 0..<5 {
            d.answer(C.ex(0, 2 + n % 4), .correct, context: .review, session: "r")
        }
        d.answer(C.ex(0, 2), .correct, context: .review, session: "r", attemptIndex: 2)  // not a new card
        d.answer(C.ex(0, 3), .correct, context: .lesson)
        d.record(d.factory.session(sessionId: "r", kind: .review, platform: .Mac, startedAt: 0, endedAt: 0,
                                   activeSeconds: 100))
        d.record(d.factory.session(sessionId: "l", kind: .lesson, platform: .Mac, startedAt: 0, endedAt: 0,
                                   activeSeconds: 50))
        let today = d.state.activity(day: LocalDay.dayNumber(ms: mondayNine, tzOffsetMinutes: 0))
        #expect(today.stepsCompleted == 2)
        #expect(today.cardsReviewed == 5)
        #expect(today.activeSeconds == 150)
        #expect(today.isActive)
        #expect(d.state.secondsPerCardSamples == [20])
        #expect(d.state.openReviewSessions.isEmpty)
    }
}
