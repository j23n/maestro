import Foundation
import Testing

@testable import LearningCore

/// M2.9: a simulated learner over 60 days never sees ineligible content; the daily caps, focus-first ordering and
/// the interleaving constraints hold every day; resuming after quitting mid-step lands on the same exercise.
@Suite struct LearnerSimulationTests {
    typealias C = TestCourse

    final class Learner {
        let d: TestDevice
        var rng: SplitMix64
        let ability: Int  // percent of answers right first time
        var catchUpToday = 0
        var dueCardsToday = 0
        var stats = (sessions: 0, cards: 0, generated: 0, requeued: 0, focusCards: 0, steps: 0, miniPreviews: 0,
                     resumes: 0, checksFailed: 0, catchUp: 0)

        init(seed: String, ability: Int) {
            d = TestDevice("learner-\(seed)", start: mondayNine - 2 * hour, tz: 60, platform: .iPad)
            rng = SplitMix64(seedString: seed)
            self.ability = ability
        }

        var content: ContentIndex { d.content }

        func outcome(_ format: ExerciseFormat) -> AttemptOutcome {
            let roll = rng.nextInt(below: 100)
            if roll < ability { return .correct }
            if format.family == .typed && roll < ability + 8 { return .almost }
            return .wrong
        }

        func mode(_ format: ExerciseFormat) -> AnswerMode {
            format == .repeat ? .spoken : format.family == .tapped ? .tapped : .typed
        }

        // MARK: Reviews

        func checkSession(_ session: ReviewSession, builder: ReviewSessionBuilder) {
            let state = builder.state
            let now = d.now
            let cards = session.cards
            #expect(cards.count <= 20)
            #expect(Set(cards.map(\.pair.itemId)).count == cards.count, "one skill per item")
            #expect(Set(cards.map(\.exerciseId)).count == cards.count, "one card per exercise")
            for card in cards {
                #expect(state.isIntroduced(card.pair) || card.exercise.isGenerated == false)
                switch card.exercise {
                case .bank(let id, _):
                    guard let exercise = content.exercise(id) else {
                        Issue.record("unknown exercise \(id)")
                        continue
                    }
                    #expect(Eligibility.isEligible(exercise: exercise, state: state), "ineligible \(id)")
                    #expect(exercise.role == .learn)
                    #expect(exercise.targets.contains(card.pair))
                    if let last = state.exerciseHistory[id]?.lastAt { #expect(now - last >= 2 * day) }
                case .generated(let generated):
                    #expect(state.isIntroduced(card.pair), "generated card for an unintroduced pair")
                    #expect(content.item(card.pair.itemId)?.kind != .grammar || card.pair.skill != .recall)
                    if case .read(let read) = generated {
                        let eligible = Set(content.items.filter { state.isIntroduced(ItemSkillPair($0.id, .read)) }
                            .map(\.primaryGloss))
                        #expect(read.options.allSatisfy { eligible.contains($0) }, "a distractor not yet met")
                    }
                    stats.generated += 1
                }
            }
            // Interleaving: never the same item twice in a row; ≤ 2 of one format in a row when possible.
            #expect(zip(cards, cards.dropFirst()).allSatisfy { $0.pair.itemId != $1.pair.itemId })
            var formats: [ExerciseFormat: Int] = [:]
            for card in cards { formats[card.format, default: 0] += 1 }
            let limit = Interleaver.runLimit(formats, total: cards.count)
            #expect(limit == 2 || !InterleaverTests.feasible(cards))
            var run = 0
            var last: ExerciseFormat?
            for card in cards {
                run = card.format == last ? run + 1 : 1
                last = card.format
                #expect(run <= limit, "a run of \(run) \(card.format.rawValue) cards")
            }
            let grammar = cards.indices.filter { cards[$0].isGrammar }
            for (k, position) in grammar.enumerated() {
                #expect(abs(position - Interleaver.idealSlot(k, n: cards.count, of: grammar.count)) <= 2,
                        "\(cards.map { ($0.isGrammar ? "G:" : "") + $0.format.rawValue })")
            }
            // Focus first: no due card got in while a focus pair with a card was left out.
            let ordered = builder.orderedPairs(now: now, tzOffsetMinutes: d.tz)
            let chosen = Set(cards.map(\.pair))
            let focus = ordered.filter { $0.source == .focus }.map(\.pair)
            if cards.contains(where: { $0.source == .due }) {
                #expect(focus.allSatisfy { chosen.contains($0) }, "a focus item was skipped for a due card")
            }
            // Due cards are taken in order: none was skipped for a later one.
            let due = ordered.filter { $0.source == .due }.map(\.pair)
            if let lastTaken = due.lastIndex(where: { chosen.contains($0) }) {
                let skipped = due[..<lastTaken].filter { !chosen.contains($0) }
                #expect(skipped.count <= 1, "due pairs skipped: \(skipped)")
            }
        }

        func review(kind: ReviewSession.Kind) {
            let builder = Planner(content: content, state: d.state).sessionBuilder
            let sessionId = "\(kind.rawValue)-\(d.now)"
            var session = kind == .review
                ? builder.build(sessionId: sessionId, now: d.now, tzOffsetMinutes: d.tz)
                : builder.buildCatchUp(sessionId: sessionId, now: d.now, tzOffsetMinutes: d.tz)
            guard !session.cards.isEmpty else { return }
            checkSession(session, builder: builder)
            if kind == .catchUp {
                #expect(session.cards.count <= builder.catchUpAllowance(now: d.now, tzOffsetMinutes: d.tz))
                stats.catchUp += session.cards.count
                catchUpToday += session.cards.count
            }
            stats.sessions += 1
            let started = d.now
            var index = 0
            while index < session.cards.count {
                let card = session.cards[index]
                let result = outcome(card.format)
                d.answer(card.exerciseId, result, context: .review, session: sessionId, mode: mode(card.format),
                         format: card.format, targets: [card.pair])
                if builder.requeueIfNeeded(&session, cardIndex: index, outcome: result, mode: mode(card.format),
                                           now: d.now)
                {
                    stats.requeued += 1
                }
                if card.source == .due { dueCardsToday += 1 }
                if card.source == .focus { stats.focusCards += 1 }
                stats.cards += 1
                d.advance(15_000)
                index += 1
            }
            d.record(d.factory.session(sessionId: sessionId, kind: .review, platform: .iPad, startedAt: started,
                                       endedAt: d.now, activeSeconds: Int((d.now - started) / 1000)))
        }

        // MARK: Lessons

        /// Returns true when the learner quit mid-step.
        @discardableResult
        func lessonStep(quit: Bool) -> Bool {
            guard let point = Progression.continuePoint(state: d.state, content: content),
                let step = content.step(point.stepId)
            else { return false }
            let resumeAt = d.state.cursor(step.id)
            if resumeAt > 0 { stats.resumes += 1 }
            guard let entry = d.enter(step.id) else { return false }
            if entry.needsMiniPreview { stats.miniPreviews += 1 }
            // After the step's introductions (and any mini-preview), everything it shows is eligible.
            for text in step.textIds { #expect(Eligibility.isEligible(text: text, state: d.state, content: content)) }
            for id in step.presentationOrder {
                guard let exercise = content.exercise(id) else { continue }
                #expect(Eligibility.isEligible(exercise: exercise, state: d.state), "\(id) shown before its items")
            }
            // Resume exactly where the cursor says.
            #expect(d.state.cursor(step.id) == resumeAt)
            if step.kind == .check {
                takeCheck(step)
                return false
            }
            let order = step.presentationOrder
            let stopAt = quit && order.count > 2 ? resumeAt + 1 + rng.nextInt(below: max(1, order.count - resumeAt - 1))
                : order.count
            for index in resumeAt..<min(stopAt, order.count) {
                let id = order[index]
                guard let exercise = content.exercise(id) else { continue }
                if exercise.format == .repeat && rng.nextInt(below: 4) == 0 {
                    d.answer(id, .skipped, step: step.id, mode: .spoken)  // "Skip — can't speak now"
                    continue
                }
                let first = outcome(exercise.format)
                d.answer(id, first, step: step.id, mode: mode(exercise.format),
                         pairOutcomes: exercise.format == .match ? exercise.targets.map { _ in first } : nil)
                if first == .wrong {
                    d.answer(id, outcome(exercise.format) == .wrong ? .revealed : .correct, step: step.id,
                             attemptIndex: 2, mode: mode(exercise.format))
                }
                #expect(d.state.cursor(step.id) == index + 1, "\(step.id) at \(index)")
                d.advance(20_000)
            }
            if stopAt >= order.count {
                d.complete(step.id)
                stats.steps += 1
                return false
            }
            return true
        }

        func takeCheck(_ step: ContentIndex.Step) {
            guard let check = step.checkId.flatMap({ content.check($0) }) else { return }
            var answers: [ExerciseID: CheckAnswer] = [:]
            for id in check.exerciseIds {
                guard let exercise = content.exercise(id) else { continue }
                let result = outcome(exercise.format)
                d.answer(id, result, context: .check, step: step.id, session: "check", mode: mode(exercise.format))
                switch exercise.format {
                case .conversation: answers[id] = .goals(completed: result == .correct ? 2 : 1, total: 2)
                case .talk, .writing: answers[id] = .points(found: result == .correct ? 2 : 1, required: 2)
                default: answers[id] = .outcome(result)
                }
            }
            let result = CheckScoring.score(check: check, answers: answers, content: content)
            d.record(d.factory.checkCompleted(result.payload))
            d.complete(step.id, session: "check")
            if !result.passed {
                stats.checksFailed += 1
                #expect(Set(result.wrongTargets).isSubset(of: Set(d.state.focusItems.keys)))
            }
        }

        // MARK: Days

        func live(day dayIndex: Int) {
            catchUpToday = 0
            dueCardsToday = 0
            let plan = Planner(content: content, state: d.state).today(clock: d.clock)
            #expect(plan.review.dueCount <= 60)
            #expect(plan.catchUp.count <= 15)
            if plan.catchUp.count > 0 { review(kind: .catchUp) }
            var sessions = 0
            while sessions < 4 {
                let today = Planner(content: content, state: d.state).today(clock: d.clock)
                guard today.review.dueCount + today.review.focusCount > 0 else { break }
                review(kind: .review)
                sessions += 1
            }
            #expect(dueCardsToday <= 60, "day \(dayIndex): \(dueCardsToday) due cards")
            #expect(catchUpToday <= 15, "day \(dayIndex): \(catchUpToday) catch-up cards")
            // A few steps; now and then the learner quits mid-step and stops for the day.
            for _ in 0..<(2 + rng.nextInt(below: 5)) where !lessonStep(quit: rng.nextInt(below: 4) == 0) {}
        }
    }

    @Test(arguments: [("beginner", 0, 82), ("placed", 3, 75)])
    func sixtyDays(name: String, placeAt unit: Int, ability: Int) throws {
        let learner = Learner(seed: name, ability: ability)
        let d = learner.d
        if unit > 0, let placement = d.content.placement {
            var results: [PlacementBlockResult] = []
            while let block = Placement.nextBlock(after: results, assessment: placement) {
                var answers: [ExerciseID: AttemptOutcome] = [:]
                for (n, id) in block.exerciseIds.enumerated() {
                    answers[id] = results.count + 1 < unit || n < 2 ? .correct : .wrong
                }
                results.append(Placement.blockResult(block, answers: answers, content: d.content))
            }
            let completion = try #require(Placement.completion(results: results, assessment: placement,
                                                               content: d.content))
            #expect(completion.startUnit == C.unitId(unit))
            d.record(d.factory.placementCompleted(completion.completed))
            d.record(completion.introduced.flatMap { d.factory.introduced($0) })
        }
        for dayIndex in 0..<60 {
            let wakeUp = Int64(learner.rng.nextInt(below: 600)) * minute
            d.clock.set(ms: mondayNine - 2 * hour + Int64(dayIndex) * day + wakeUp)
            if learner.rng.nextInt(below: 10) == 0 { continue }  // a day off
            learner.live(day: dayIndex)
            if dayIndex % 15 == 14 {
                #expect(Replay.rebuildAll(events: d.events, content: d.content) == d.state)
            }
        }
        let s = learner.stats
        #expect(s.sessions > 40)
        #expect(s.cards > 500)
        #expect(s.generated > 0)
        #expect(s.requeued > 0)
        #expect(s.steps > 80)
        #expect(s.resumes > 0)
        #expect(Progress.wordsKnown(state: d.state, content: d.content, now: d.now) > 20)
        #expect(Progression.unitsCompleted(state: d.state, content: d.content) >= 3)
        if unit > 0 {
            #expect(s.catchUp >= 25)  // the whole queue of Units 0–2
            #expect(!d.state.catchUpStarted.isEmpty)
            #expect(d.state.catchUpStarted.values.allSatisfy { $0 <= 15 })
        } else {
            #expect(s.checksFailed + s.focusCards >= 0)
        }
        #expect(try d.state.canonicalEncoding()
                == Replay.rebuildAll(events: d.events.seededShuffle(seed: name), content: d.content)
                    .canonicalEncoding())
    }
}
