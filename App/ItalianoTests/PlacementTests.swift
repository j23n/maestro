import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// M8.1 (docs/05 § Placement, docs/06 §19): a scripted learner sits placement through the app's model and the real
/// exercise models, is placed at Unit 3, and finds catch-up cards waiting; "Start from the beginning"; the offer
/// after onboarding.
@MainActor
@Suite struct PlacementTests {
    typealias A = AssessmentCourse
    let folder = FileManager.default.temporaryDirectory
        .appendingPathComponent("italiano-placement-\(UUID().uuidString)", isDirectory: true)
    let clock = FixedClock(ms: 1_791_271_800_000, tzOffsetMinutes: 120)  // Tue 6 Oct 2026, 09:30 in Rome

    func openStore() async throws -> LearnerStore {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return try await LearnerStore.open(
            url: folder.appendingPathComponent("learner.sqlite"), content: A.content, clock: clock,
            ids: SeededUUIDSource(seed: "placement"))
    }

    /// A placement sitting with every attempt collected as an event.
    func sitting(factory: EventFactory) throws -> (PlacementSessionModel, () -> [Event]) {
        var events: [Event] = []
        let sink = EventAttemptSink(factory: factory, context: .placement, sessionID: "s-placement") {
            events.append($0)
        }
        let session = try #require(PlacementSession(assessment: A.content.placement, content: A.content))
        let model = PlacementSessionModel(
            session: session, content: A.content, bundle: A.bundle(try A.placementPayloads()),
            env: .preview(context: .placement), sink: sink)
        return (model, { events })
    }

    /// Answers like a learner: in block b, the first `right[b]` items right, the others wrong; each item once.
    func answer(_ model: PlacementSessionModel, right: [Int]) throws {
        while model.phase == .playing {
            guard case .choice(let m) = model.host else {
                Issue.record("placement items are choice questions here")
                return
            }
            let correct = model.session.position < right[model.session.results.count]
            m.select(correct ? m.correctIndex : (m.correctIndex + 1) % m.options.count)
            #expect(m.isDone)  // one attempt, no feedback: the item is over
            m.select(m.correctIndex)  // nothing more is recorded
            model.advance()
        }
    }

    @Test func aScriptedLearnerIsPlacedAtUnitThreeAndCatchUpCardsAppear() async throws {
        let store = try await openStore()
        let factory = try await store.makeEventFactory(
            packVersion: A.content.packVersion, ids: SeededUUIDSource(seed: "f"))
        let (model, events) = try sitting(factory: factory)
        #expect(model.phase == .intro && model.progress == 0 && model.host == nil && !model.hasStarted)
        model.start()
        #expect(model.blockLine == "Unit 1 questions")
        #expect(model.session.maximumCount == 40)
        try answer(model, right: [5, 4, 2])

        #expect(model.phase == .result && model.progress == 1)
        #expect(model.session.results.map(\.correct) == [5, 4, 2])
        #expect(model.startUnit == "u03")
        let completion = try #require(model.completion)
        let result = PlacementResultContent(startUnit: "u03", content: A.content, outline: A.outline)
        #expect(result.headline == "We'll start you at Unit 3:" && result.titleIt == "Unità 3")
        #expect(result.detail.hasPrefix("Units 0 to 2 are marked as skipped."))

        // One attempt per item, context placement, no feedback shown.
        let attempts = events().compactMap { e -> AttemptPayload? in
            if case .attempt(let a) = e.payload { a } else { nil }
        }
        #expect(attempts.count == 15)
        #expect(attempts.allSatisfy { $0.context == .placement && $0.attemptIndex == 1 && $0.feedbackShown == .none })
        #expect(attempts.allSatisfy { $0.sessionId == "s-placement" && $0.stepId == nil })

        // "Start there": placementCompleted and the introductions, through the real learner store.
        let written = AppModel.placementEvents(completion, factory: factory)
        #expect(written.map(\.type) == ["placementCompleted", "introduced"])
        let state = try await store.append(events() + written).state
        #expect(state.placement?.startUnit == "u03")
        #expect((0...2).allSatisfy { state.unitState(A.unit($0)) == .skipped })
        #expect(state.unitState("u03") == .available && state.unitState("u04") == .locked)
        #expect(state.memory.isEmpty)  // FSRS state comes from real reviews only
        #expect(state.introductions.values.allSatisfy { $0.via == .placement })
        #expect(
            Set(state.introductions.keys.map(\.itemId)) == Set((0...2).flatMap { k in (1...6).map { A.word(k, $0) } }))

        // Today: 18 scheduled pairs wait, 15 of them today.
        let planner = Planner(content: A.content, state: state)
        let plan = planner.today(clock: clock)
        #expect(plan.catchUp.waiting == 18 && plan.catchUp.count == 15)
        #expect(plan.review.dueCount == 0)
        let card = TodayCopy.review(plan, words: [:])
        #expect(card.catchUp == "15 catch-up cards from placement")
        #expect(card.body == "No reviews due. Your catch-up cards are ready.")

        // Start review → the catch-up session (nothing is due), every card playable.
        let session = planner.sessionBuilder.buildCatchUp(
            sessionId: "s-catchup", now: clock.nowMs(), tzOffsetMinutes: clock.tzOffsetMinutes())
        #expect(session.cards.count == 15 && session.cards.allSatisfy { $0.source == .catchUp })
        #expect(session.cards.allSatisfy { A.content.item($0.pair.itemId)?.unitId.rawValue ?? "" < "u03" })
        let review = ReviewSessionModel(
            session: session, builder: planner.sessionBuilder, env: .preview(context: .review), sink: nil,
            newPairs: Set(session.cards.map(\.pair)),
            payloads: { card in
                guard case .generated(let g) = card.exercise else { return nil }
                return GeneratedPayloads.payload(for: g, unit: "u00", display: { _ in nil })
            })
        #expect(review.host != nil && review.index == 0)
        try store.close()
    }

    @Test func startFromTheBeginningAtAnyPointWritesUnitZeroAndNoIntroductions() async throws {
        let store = try await openStore()
        let factory = try await store.makeEventFactory(
            packVersion: A.content.packVersion, ids: SeededUUIDSource(seed: "f"))
        let (model, events) = try sitting(factory: factory)
        model.start()
        // Unit 1's block, then one item of Unit 2's, then the learner leaves.
        for _ in 0..<6 {
            guard case .choice(let m) = model.host else { break }
            m.select(m.correctIndex)
            model.advance()
        }
        #expect(model.completion == nil)  // blocks remain
        let start = try #require(model.fromBeginning)
        #expect(start.startUnit == "u00" && start.introduced == nil)
        #expect(start.completed.blocks.map(\.unit) == ["u01"])
        let written = AppModel.placementEvents(start, factory: factory)
        #expect(written.map(\.type) == ["placementCompleted"])
        let state = try await store.append(events() + written).state
        #expect(state.placement?.startUnit == "u00")
        #expect(state.introductions.isEmpty && state.unitState("u00") == .available)
        #expect(Planner(content: A.content, state: state).today(clock: clock).catchUp.waiting == 0)
        try store.close()
    }

    @Test func theOfferStandsUntilPlacementOrTheFirstStep() throws {
        var state = Replay.initialState(content: A.content)
        #expect(AppModel.mayStillOfferPlacement(state: state))
        let factory = EventFactory(
            deviceId: "d", packVersion: "0.9.0", clock: clock, ids: SeededUUIDSource(seed: "offer"))
        Replay.reduce(&state, factory.placementCompleted(.init(startUnit: "u00", blocks: [])), content: A.content)
        #expect(!AppModel.mayStillOfferPlacement(state: state))
        var started = Replay.initialState(content: A.content)
        if let e = factory.introduced([ItemSkillPair(A.word(0, 1), .read)], via: .preview) {
            Replay.reduce(&started, e, content: A.content)
        }
        #expect(!AppModel.mayStillOfferPlacement(state: started))
    }

    @Test func oneSkippedUnitReadsInTheSingular() {
        let r = PlacementResultContent(startUnit: "u01", content: A.content, outline: A.outline)
        #expect(r.headline == "We'll start you at Unit 1:")
        #expect(
            r.detail == "Unit 0 is marked as skipped. Its words join your reviews as catch-up cards, up to 15 a day.")
    }

    /// The mini pack has no placement questions: "Yes, I know a little" goes straight to Today, and "Start from the
    /// beginning" still writes `placementCompleted` at Unit 0 through the app container.
    @Test func withoutPlacementQuestionsTheLearnerGoesStraightToToday() async throws {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let app = AppModel(
            env: .init(
                packURL: PackAdaptersTests.packURL, learnerURL: folder.appendingPathComponent("learner.sqlite"),
                clock: clock, ids: SeededUUIDSource(seed: "mini"), platform: .iPhone))
        await app.start()
        #expect(app.phase == .ready && !app.canRunPlacement)
        app.completeOnboarding(
            .init(reason: "travel", name: "", forms: .both, country: nil, goal: 5, beginner: false, consent: nil))
        #expect(app.isOnboarded && !app.placementPending)
        #expect(try await app.startPlacement() == nil)
        app.startFromTheBeginning(launch: nil, activeSeconds: 0)
        await app.settle()
        #expect(app.state?.placement?.startUnit == "u00")
        #expect(app.state?.introductions.isEmpty == true)
    }
}
