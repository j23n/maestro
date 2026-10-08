import Foundation
import Testing

@testable import LearningCore

/// A state with every item of the first `units` introduced (per status) and memory for each scheduled pair, due
/// `dueOffset(pair)` from `now`.
func plannedState(units: Int, content: ContentIndex = TestCourse.standard, now: Int64 = mondayNine,
                  dueOffset: (ItemSkillPair, Int) -> Int64) -> LearnerState
{
    let d = TestDevice(content: content, start: now - 30 * day)
    if let payload = Introductions.placementPayload(startUnit: TestCourse.unitId(units), content: content) {
        d.record(d.factory.introduced(payload))
    }
    var state = d.state
    var n = 0
    for pair in content.scheduledPairs where state.isIntroduced(pair) {
        let due = now + dueOffset(pair, n)
        state.memory[pair] = MemoryState(stability: 5 + Double(n % 7), difficulty: 5, lastReviewMs: due - 5 * day,
                                         dueMs: due, reps: 2, lapses: 0)
        n += 1
    }
    return state
}

@Suite struct ReviewSessionTests {
    typealias C = TestCourse
    let content = TestCourse.standard

    @Test func orderIsFocusThenDueThenRetrievabilityThenID() {
        var state = plannedState(units: 2) { _, n in Int64(n % 5) * hour - 3 * day }
        let focus = ItemSkillPair(C.noun(1, 1), .listen)  // a focus pair, not scheduled, no memory
        let focusDue = ItemSkillPair(C.noun(1, 2), .recall)
        state.focusItems[focus] = FocusItem(reason: "check:u01.check", until: mondayNine + day)
        state.focusItems[focusDue] = FocusItem(reason: "check:u01.check", until: mondayNine + day)
        state.focusItems[ItemSkillPair(C.noun(1, 3), .recall)] = FocusItem(reason: "old", until: mondayNine - 1)
        let builder = ReviewSessionBuilder(content: content, state: state)
        let ordered = builder.orderedPairs(now: mondayNine, tzOffsetMinutes: 0)
        #expect(ordered.prefix(2).map(\.pair) == [focus, focusDue])  // no memory sorts first among focus
        #expect(ordered.prefix(2).allSatisfy { $0.source == .focus })
        let due = ordered.dropFirst(2)
        #expect(due.allSatisfy { $0.source == .due })
        #expect(zip(due, due.dropFirst()).allSatisfy { a, b in
            (a.due ?? 0, a.retrievability) < (b.due ?? 0, b.retrievability)
                || ((a.due ?? 0, a.retrievability) == (b.due ?? 0, b.retrievability) && a.pair < b.pair)
        })
        // At most one skill per item: noun 1-1's scheduled recall waits behind its focus listen card.
        #expect(!ordered.contains { $0.pair == ItemSkillPair(C.noun(1, 1), .recall) })
        // A focus pair with no card at all (no exercise, nothing to generate) waits.
        var noCard = state
        noCard.focusItems = [ItemSkillPair(C.noun(1, 4), .listen): FocusItem(reason: "x", until: mondayNine + day)]
        #expect(!ReviewSessionBuilder(content: content, state: noCard).orderedPairs(now: mondayNine, tzOffsetMinutes: 0)
            .contains { $0.source == .focus })
        #expect(Set(ordered.map(\.pair.itemId)).count == ordered.count)
        // An expired focus item is an ordinary due pair.
        #expect(ordered.first { $0.pair.itemId == C.noun(1, 3) }?.source == .due)
    }

    @Test func notDueAndIneligiblePairsAreLeftOut() {
        let state = plannedState(units: 1) { pair, _ in pair.itemId == C.noun(0, 1) ? 2 * day : -day }
        let ordered = ReviewSessionBuilder(content: content, state: state).orderedPairs(now: mondayNine,
                                                                                      tzOffsetMinutes: 0)
        #expect(!ordered.contains { $0.pair.itemId == C.noun(0, 1) })
        #expect(!ordered.isEmpty)
        // Due by the end of today (04:00 tomorrow, 19 hours after 09:00) counts.
        let late = plannedState(units: 1) { _, _ in 19 * hour }
        #expect(ReviewSessionBuilder(content: content, state: late).orderedPairs(now: mondayNine, tzOffsetMinutes: 0)
            .count == 10)  // all of Unit 0: 4 nouns, adverb, chunk, story word, two grammar points, sound
        let tomorrow = plannedState(units: 1) { _, _ in 19 * hour + minute }
        #expect(ReviewSessionBuilder(content: content, state: tomorrow).orderedPairs(now: mondayNine,
                                                                                     tzOffsetMinutes: 0).isEmpty)
    }

    @Test func sessionsHoldAtMostTwentyCardsWithDistinctExercises() throws {
        let state = plannedState(units: 6) { _, n in -Int64(n) * minute }
        let builder = ReviewSessionBuilder(content: content, state: state)
        let ordered = builder.orderedPairs(now: mondayNine, tzOffsetMinutes: 0)
        #expect(ordered.count > 20)
        let session = builder.build(sessionId: "s-1", now: mondayNine, tzOffsetMinutes: 0)
        #expect(session.cards.count == 20)
        #expect(Set(session.cards.map(\.exerciseId)).count == 20)
        #expect(Set(session.cards.map(\.pair)) == Set(ordered.prefix(20).map(\.pair)))
        for card in session.cards {
            if case .bank(let id, _) = card.exercise {
                let exercise = try #require(content.exercise(id))
                #expect(Eligibility.isEligible(exercise: exercise, state: state))
                #expect(exercise.targets.contains(card.pair))
            } else {
                #expect(state.isIntroduced(card.pair))
            }
        }
        // Deterministic per session ID.
        #expect(builder.build(sessionId: "s-1", now: mondayNine, tzOffsetMinutes: 0) == session)
        #expect(builder.build(sessionId: "s-2", now: mondayNine, tzOffsetMinutes: 0).cards.map(\.pair)
                != session.cards.map(\.pair))
    }

    @Test func dueCardsStopAtTheDailyLimitFocusCardsDoNot() {
        var state = plannedState(units: 4) { _, n in -Int64(n) * minute }
        let today = LocalDay.dayNumber(ms: mondayNine, tzOffsetMinutes: 0)
        state.dailyActivity[today] = DailyActivity(day: today, cardsReviewed: 57)
        let focus = ItemSkillPair(C.noun(3, 1), .listen)
        state.focusItems[focus] = FocusItem(reason: "check:u03.check", until: mondayNine + day)
        let builder = ReviewSessionBuilder(content: content, state: state)
        #expect(builder.remainingDailyAllowance(now: mondayNine, tzOffsetMinutes: 0) == 3)
        let session = builder.build(sessionId: "s", now: mondayNine, tzOffsetMinutes: 0)
        #expect(session.cards.filter { $0.source == .due }.count == 3)
        #expect(session.cards.filter { $0.source == .focus }.map(\.pair) == [focus])
        let plan = Planner(content: content, state: state).today(now: mondayNine, tzOffsetMinutes: 0)
        #expect(plan.review.dueCount == 3)
        #expect(plan.review.dueTotal > 3)
    }

    @Test func aFocusPairReviewedTodayWaitsUntilTomorrow() {
        var state = plannedState(units: 1) { _, _ in 5 * day }
        let pair = ItemSkillPair(C.noun(0, 1), .recall)
        state.focusItems[pair] = FocusItem(reason: "check:u00.check", until: mondayNine + 3 * day)
        state.memory[pair]?.lastReviewMs = mondayNine - hour
        let builder = ReviewSessionBuilder(content: content, state: state)
        #expect(builder.orderedPairs(now: mondayNine, tzOffsetMinutes: 0).isEmpty)
        #expect(builder.orderedPairs(now: mondayNine + day, tzOffsetMinutes: 0).map(\.pair) == [pair])
    }

    @Test func againCardsAreRequeuedOnceWithADifferentExercise() throws {
        let state = plannedState(units: 2) { _, n in -Int64(n) * minute }
        let builder = ReviewSessionBuilder(content: content, state: state, sessionTarget: 6)
        var session = builder.build(sessionId: "rq", now: mondayNine, tzOffsetMinutes: 0)
        #expect(session.cards.count == 6)
        let first = session.cards[0]
        #expect(!builder.requeueIfNeeded(&session, cardIndex: 1, outcome: .correct, mode: .typed, now: mondayNine))
        #expect(!builder.requeueIfNeeded(&session, cardIndex: 2, outcome: .skipped, mode: .typed, now: mondayNine))
        #expect(builder.requeueIfNeeded(&session, cardIndex: 0, outcome: .wrong,
                                        mode: first.format.family == .tapped ? .tapped : .typed, now: mondayNine))
        #expect(session.cards.count == 7)
        let again = try #require(session.cards.last)
        #expect(again.pair == first.pair)
        #expect(again.isRequeue)
        #expect(again.exerciseId != first.exerciseId)
        // Only once per pair, and never a re-queued card.
        #expect(!builder.requeueIfNeeded(&session, cardIndex: 0, outcome: .wrong, mode: .typed, now: mondayNine))
        #expect(!builder.requeueIfNeeded(&session, cardIndex: 6, outcome: .wrong, mode: .typed, now: mondayNine))
        // A failed spoken answer is not Again (no update), so no re-queue.
        let spoken = session.cards.firstIndex { !$0.isRequeue && $0.pair != first.pair } ?? 1
        #expect(!builder.requeueIfNeeded(&session, cardIndex: spoken, outcome: .wrong, mode: .spoken, now: mondayNine))
        #expect(session.cards.count == 7)
    }

    @Test func catchUpCardsAreCappedAtFifteenADay() {
        let d = TestDevice()
        d.record(d.factory.placementCompleted(PlacementCompletedPayload(startUnit: "u04", blocks: [])))
        let payload = Introductions.placementPayload(startUnit: "u04", content: content)
        d.record(payload.flatMap { d.factory.introduced($0) })
        let builder = ReviewSessionBuilder(content: content, state: d.state)
        let waiting = builder.catchUpPairs(now: d.now)
        #expect(waiting.count == d.content.scheduledPairs.filter { d.state.introductions[$0]?.via == .placement }.count)
        #expect(waiting.first?.itemId.rawValue.contains("u00") == true)  // course order
        let session = builder.buildCatchUp(sessionId: "c1", now: d.now, tzOffsetMinutes: 0)
        #expect(session.cards.count == 15)
        #expect(session.cards.allSatisfy { $0.source == .catchUp })
        // Answer 10 of them: 5 left today, 15 tomorrow.
        for card in session.cards.prefix(10) {
            d.answer(card.exerciseId, .correct, context: .review, session: "c1", format: card.format,
                     targets: [card.pair])
        }
        let after = ReviewSessionBuilder(content: content, state: d.state)
        #expect(after.catchUpAllowance(now: d.now, tzOffsetMinutes: 0) == 5)
        #expect(after.buildCatchUp(sessionId: "c2", now: d.now, tzOffsetMinutes: 0).cards.count == 5)
        #expect(after.catchUpAllowance(now: d.now + day, tzOffsetMinutes: 0) == 15)
        #expect(after.catchUpPairs(now: d.now).count == waiting.count - 10)
    }
}

@Suite struct InterleaverTests {
    static let formats: [ExerciseFormat] = [.recall, .cloze, .choice, .match, .sentenceBuilding, .dictation]

    func cards(_ specs: [(ExerciseFormat, Bool)]) -> [ReviewCard] {
        specs.enumerated().map { n, spec in
            ReviewCard(pair: ItemSkillPair(ItemID(spec.1 ? "g:\(n)" : "w:\(n)"), .recall), source: .due,
                       exercise: .bank(ExerciseID("e\(n)"), spec.0), itemKind: spec.1 ? .grammar : .word)
        }
    }

    func maxRun(_ cards: [ReviewCard]) -> Int {
        var best = 0
        var run = 0
        var last: ExerciseFormat?
        for card in cards {
            run = card.format == last ? run + 1 : 1
            last = card.format
            best = max(best, run)
        }
        return best
    }

    static func feasible(_ cards: [ReviewCard]) -> Bool {
        var counts: [ExerciseFormat: Int] = [:]
        for c in cards { counts[c.format, default: 0] += 1 }
        return counts.values.allSatisfy { $0 <= 2 * (cards.count - $0 + 1) }
    }

    @Test func randomSessionsKeepTheConstraints() {
        var feasibleRuns = 0
        for seed in 0..<500 {
            var gen = SplitMix64(seedString: "cards-\(seed)")
            let n = 1 + gen.nextInt(below: 20)
            let skew = gen.nextInt(below: 4)  // some sessions are mostly one format
            let specs = (0..<n).map { _ -> (ExerciseFormat, Bool) in
                let format =
                    gen.nextInt(below: 4) < skew ? .recall : Self.formats[gen.nextInt(below: Self.formats.count)]
                return (format, gen.nextInt(below: 4) == 0)
            }
            let input = cards(specs)
            var rng = SplitMix64(seedString: "session-\(seed)")
            let out = Interleaver.interleave(input, rng: &rng)
            #expect(out.count == input.count)
            #expect(Set(out.map(\.exerciseId)) == Set(input.map(\.exerciseId)))
            var counts: [ExerciseFormat: Int] = [:]
            for card in input { counts[card.format, default: 0] += 1 }
            if Self.feasible(input) {
                feasibleRuns += 1
                #expect(maxRun(out) <= 2, "seed \(seed)")
            } else {
                // The smallest achievable maximum run instead.
                #expect(maxRun(out) == Interleaver.runLimit(counts, total: input.count), "seed \(seed)")
            }
            var again = SplitMix64(seedString: "session-\(seed)")
            #expect(Interleaver.interleave(input, rng: &again) == out)
        }
        #expect(feasibleRuns > 300)
    }

    @Test func neverTheSameItemTwiceInARow() {
        // Two cards of one item (a re-queue built into a list) are separated whenever possible.
        var input = cards([(.recall, false), (.cloze, false), (.choice, false), (.match, false)])
        input.append(ReviewCard(pair: input[0].pair, source: .due, exercise: .bank("e-again", .dictation),
                                itemKind: .word))
        for seed in 0..<50 {
            var rng = SplitMix64(seedString: "same-\(seed)")
            let out = Interleaver.interleave(input, rng: &rng)
            #expect(zip(out, out.dropFirst()).allSatisfy { $0.pair.itemId != $1.pair.itemId })
        }
    }

    @Test func grammarCardsAreSpreadEvenly() {
        for seed in 0..<200 {
            var gen = SplitMix64(seedString: "g-\(seed)")
            let n = 8 + gen.nextInt(below: 13)
            let g = 1 + gen.nextInt(below: n / 3)
            let specs = (0..<n).map { i in (Self.formats[gen.nextInt(below: Self.formats.count)], i < g) }
            var rng = SplitMix64(seedString: "spread-\(seed)")
            let out = Interleaver.interleave(cards(specs), rng: &rng)
            let positions = out.indices.filter { out[$0].isGrammar }
            #expect(positions.count == g)
            for (k, position) in positions.enumerated() {
                let ideal = Interleaver.idealSlot(k, n: n, of: g)
                #expect(abs(position - ideal) <= 2, "seed \(seed): grammar \(k) at \(position), ideal \(ideal)")
            }
        }
    }

    @Test func impossibleRunsAreRelaxedNotDropped() {
        let all = cards(Array(repeating: (.recall, false), count: 7))
        var rng = SplitMix64(seed: 9)
        #expect(Interleaver.interleave(all, rng: &rng).count == 7)
        #expect(Interleaver.interleave([], rng: &rng).isEmpty)
        // 15 recall among 18: runs of at most ⌈15/4⌉ = 4, and the two grammar cards still near slots 4 and 13.
        let mostlyRecall = cards(Array(repeating: (ExerciseFormat.recall, false), count: 15)
                                 + [(.cloze, true), (.cloze, true), (.choice, false)])
        #expect(Interleaver.runLimit([.recall: 15, .cloze: 2, .choice: 1], total: 18) == 4)
        for seed in 0..<50 {
            var r = SplitMix64(seedString: "mostly-\(seed)")
            let out = Interleaver.interleave(mostlyRecall, rng: &r)
            #expect(maxRun(out) == 4)
            let grammar = out.indices.filter { out[$0].isGrammar }
            #expect(abs(grammar[0] - 4) <= 2 && abs(grammar[1] - 13) <= 2, "\(grammar)")
        }
    }
}

@Suite struct PlannerTests {
    typealias C = TestCourse
    let content = TestCourse.standard

    @Test func todayCountsDueCardsWithAnEstimateAndExamples() {
        let state = plannedState(units: 2) { _, n in -Int64(n) * minute }
        let planner = Planner(content: content, state: state)
        let plan = planner.today(now: mondayNine, tzOffsetMinutes: 0)
        let ordered = planner.sessionBuilder.orderedPairs(now: mondayNine, tzOffsetMinutes: 0)
        #expect(plan.review.dueCount == ordered.count)
        #expect(plan.review.secondsPerCard == 18)
        #expect(plan.review.estimatedMinutes == Int((Double(ordered.count) * 18 / 60).rounded(.up)))
        #expect(plan.review.exampleItems == ordered.prefix(2).map(\.pair.itemId))
        #expect(!plan.reviewIsPrimary)
        #expect(plan.stats.unitsTotal == 13)
        #expect(plan.continuePoint?.stepId == C.unitStep(0, "opener"))
    }

    @Test func theEstimateUsesTheLearnersMedianSecondsPerCard() {
        var state = plannedState(units: 1) { _, _ in -day }
        state.secondsPerCardSamples = [10, 30, 12, 40]
        let plan = Planner(content: content, state: state).today(now: mondayNine, tzOffsetMinutes: 0)
        #expect(plan.review.secondsPerCard == 21)
        #expect(plan.review.estimatedMinutes == Int((Double(plan.review.dueCount) * 21 / 60).rounded(.up)))
        #expect(Planner.median([3, 1, 2]) == 2)
        #expect(Planner.median([]) == nil)
    }

    @Test func reviewIsPrimaryAboveFortyAndCappedAtTheDailyLimit() {
        let state = plannedState(units: 8) { _, n in -Int64(n) * minute }
        let plan = Planner(content: content, state: state).today(now: mondayNine, tzOffsetMinutes: 0)
        #expect(plan.review.dueTotal > 60)
        #expect(plan.review.dueCount == 60)
        #expect(plan.reviewIsPrimary)
        let small = Planner(content: content, state: state, settings: PlannerSettings(dailyReviewLimit: 40))
            .today(now: mondayNine, tzOffsetMinutes: 0)
        #expect(small.review.dueCount == 40)
        #expect(!small.reviewIsPrimary)
    }

    @Test func settingsFeedThePlanner() {
        let settings = LearnerSettings(records: [
            SettingRecord(.reviewDailyLimit, value: .number(25), updatedAt: 1, deviceId: "a"),
            SettingRecord(.goalDaysPerWeek, value: .number(3), updatedAt: 1, deviceId: "a"),
        ])
        let planner = PlannerSettings(settings)
        #expect(planner.dailyReviewLimit == 25)
        #expect(planner.weeklyGoal == 3)
        let state = plannedState(units: 4) { _, n in -Int64(n) * minute }
        let plan = Planner(content: content, state: state, settings: planner).today(now: mondayNine, tzOffsetMinutes: 0)
        #expect(plan.review.dueCount == 25)
        #expect(plan.week.goal == 3)
    }

    @Test func placementFillsTheCatchUpQueue() {
        let d = TestDevice()
        d.record(d.factory.placementCompleted(PlacementCompletedPayload(startUnit: "u03", blocks: [])))
        let payload = Introductions.placementPayload(startUnit: "u03", content: content)
        d.record(payload.flatMap { d.factory.introduced($0) })
        let plan = Planner(content: content, state: d.state).today(now: d.now, tzOffsetMinutes: 0)
        #expect(plan.catchUp.count == 15)
        #expect(plan.catchUp.waiting > 15)
        #expect(plan.review.dueCount == 0)
        #expect(plan.continuePoint?.unitId == "u03")
    }

    @Test func statsAndWeek() {
        let d = TestDevice()
        d.runUnit(0)
        d.runUnit(1, checkPassed: false)
        let plan = Planner(content: content, state: d.state).today(clock: d.clock)
        #expect(plan.stats.unitsCompleted == 2)
        #expect(plan.week.activeDays == 1)
        #expect(plan.week.days[0])
        #expect(plan.continuePoint?.unitId == "u02")
        #expect(plan.catchUp.count == 0)
    }
}
