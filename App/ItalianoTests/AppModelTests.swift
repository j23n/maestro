import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// The launch path end to end on the mini pack and a throwaway learner database: open, plan Today, play the start
/// of the golden lesson through the real engine, and resume after a relaunch.
@MainActor
@Suite struct AppModelTests {
    let folder = FileManager.default.temporaryDirectory
        .appendingPathComponent("italiano-app-\(UUID().uuidString)", isDirectory: true)
    let clock = FixedClock(ms: 1_791_271_800_000, tzOffsetMinutes: 120)  // Tue 6 Oct 2026, 09:30 in Rome

    func model(_ seed: String = "a") -> AppModel {
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return AppModel(
            env: .init(
                packURL: PackAdaptersTests.packURL, learnerURL: folder.appendingPathComponent("learner.sqlite"),
                clock: clock, ids: SeededUUIDSource(seed: seed), platform: .iPhone))
    }

    @Test func launchesOnTheMiniPack() async throws {
        let app = model()
        await app.start()
        #expect(app.phase == .ready)
        #expect(app.outline.units.map(\.number) == [0, 1, 2])
        let today = try #require(app.today)
        #expect(today.greeting == "Buongiorno" && today.dateLine == "Tuesday, October 6")
        #expect(app.courseRows.count == 3)
        #expect(app.recoveryNotice == nil)
    }

    @Test func playingWritesEventsAndResumes() async throws {
        let app = model()
        await app.start()
        let launch = try #require(try await app.launch(step: "u02.l1.step-preview"))
        let player = launch.model
        launch.sink.stepID = player.currentStep?.id  // as LessonPlayerView does
        if let first = player.openingStep {
            app.stepChanged(.init(completed: nil, started: first), sessionID: launch.sessionID)
        }
        // Meet cards, then answer the preview's exercises as they come (first option / give up: any outcome counts).
        var answered = 0
        while answered < 2, !player.isFinished {
            if let payload = player.currentExercise,
                let host = ExerciseHostModel.make(payload, env: launch.environment, sink: launch.sink)
            {
                answerSomehow(host)
                answered += 1
            }
            let change = player.advance()
            launch.sink.stepID = player.currentStep?.id
            app.stepChanged(change, sessionID: launch.sessionID)
        }
        app.endSession(launch, activeSeconds: 42)
        await app.settle()
        let state = try #require(app.state)
        #expect(state.stepProgress("u02.l1.step-preview")?.startedAt != nil)
        #expect(!(state.stepProgress("u02.l1.step-preview")?.finalExercises.isEmpty ?? true))
        #expect(
            state.introductions.keys.contains {
                $0.itemId.rawValue.hasPrefix("w:") || $0.itemId.rawValue.hasPrefix("c:")
            })

        // Your words: the preview introduced words, not reviewed yet, so they are new and due nowhere.
        let rows = app.wordRows
        #expect(!rows.isEmpty && rows.allSatisfy { $0.status == .new || $0.status == .learning })
        #expect(rows.allSatisfy { $0.bars.count == 4 })
        #expect(WordsCopy.counts(rows)[.all] == rows.count)

        // Relaunch: the same database, a fresh model; the lesson resumes after what was answered.
        let again = model("b")
        await again.start()
        let resumed = try #require(try await again.launch(step: "u02.l1.step-preview"))
        #expect(resumed.model.exerciseNumber >= 2)
        #expect(again.today?.continueCard?.unitID == "u02")
    }

    @Test func settingsPersist() async throws {
        let app = model()
        await app.start()
        app.set(.goalDaysPerWeek, to: .number(3))
        app.set(.profileForms, to: .string("f"))
        await app.settle()
        #expect(app.settings.goalDaysPerWeek == 3 && app.profile.forms == .f)
        let again = model("b")
        await again.start()
        #expect(again.settings.goalDaysPerWeek == 3)
        #expect(again.today?.weekLine.hasSuffix("of 3 days") == true)
    }

    @Test func aMissingPackFailsToLaunch() async {
        let app = AppModel(
            env: .init(
                packURL: folder.appendingPathComponent("nope.sqlite"),
                learnerURL: folder.appendingPathComponent("l.sqlite"),
                clock: clock, ids: SeededUUIDSource(seed: "c"), platform: .Mac))
        await app.start()
        guard case .failed = app.phase else {
            Issue.record("expected a launch failure, got \(app.phase)")
            return
        }
    }

    @Test func aReviewSessionPlaysDueCards() async throws {
        let app = model()
        await app.start()
        #expect(try await app.startReview() == nil)  // nothing met yet, nothing to review
        let launch = try #require(try await app.launch(step: "u02.l1.step-preview"))
        launch.sink.stepID = "u02.l1.step-preview"
        if let first = launch.model.openingStep {
            app.stepChanged(.init(completed: nil, started: first), sessionID: launch.sessionID)
        }
        var guardCount = 0
        while !launch.model.isFinished, launch.model.currentStep?.id == "u02.l1.step-preview", guardCount < 40 {
            if let p = launch.model.currentExercise,
                let h = ExerciseHostModel.make(
                    p, env: launch.environment,
                    sink: launch.sink)
            {
                answerSomehow(h)
            }
            let change = launch.model.advance()
            launch.sink.stepID = launch.model.currentStep?.id
            app.stepChanged(change, sessionID: launch.sessionID)
            guardCount += 1
        }
        await app.settle()
        clock.advance(byMs: 10 * 86_400_000)  // ten days later, the preview's words are due
        let review = try #require(try await app.startReview())
        let session = review.model
        #expect(!session.isFinished && session.host != nil)
        var cards = 0
        while !session.isFinished, cards < 60 {
            if let h = session.host { answerSomehow(h) }
            session.advance()
            cards += 1
        }
        #expect(session.isFinished)
        #expect(session.summary.total > 0 && session.summary.remembered <= session.summary.total)
        let complete = CompleteContent(
            summary: session.summary, words: [:], nextReview: "Tomorrow",
            week: WeekProgress(
                weekStart: 0, days: [true, true, true, true, false, false, false],
                goal: 5))
        #expect(complete.remembered == "\(session.summary.remembered) of \(session.summary.total)")
        #expect(complete.weekLine == "4 of 5 days this week. One more and you've met your goal.")
        app.endSession(sessionID: review.sessionID, kind: .review, startedAt: review.startedAt, activeSeconds: 60)
        await app.settle()
        #expect(app.nextReview != nil && app.week != nil)
        #expect((app.state?.memory.count ?? 0) > 0)
    }

    @Test func theUnitCheckScoresAndIsRecorded() async throws {
        let app = model()
        await app.start()
        let launch = try #require(try await app.launch(step: "u02.step-check"))
        #expect(launch.kind == .check && launch.environment.context == .check)
        launch.sink.stepID = launch.model.currentStep?.id
        var answered = 0
        var guardCount = 0
        while !launch.model.isFinished, guardCount < 60 {
            if let p = launch.model.currentExercise,
                let h = ExerciseHostModel.make(p, env: launch.environment, sink: launch.sink)
            {
                answerSomehow(h)
                answered += 1
            }
            _ = launch.model.advance()
            guardCount += 1
        }
        #expect(answered > 0)
        let result = try #require(app.completeCheck(launch))
        #expect(!result.sections.isEmpty && result.overall.hasSuffix("%"))
        await app.settle()
        let unit = try #require(app.state?.units["u02"])
        #expect(unit.checkScore != nil)
    }

    @Test func generatedCardsBecomePayloads() throws {
        let recall = GeneratedRecallCard(
            exerciseId: "gen:recall:w:caffe", itemId: "w:caffe", promptEn: "coffee",
            answer: "{il|un} [caffè]", near: [])
        let p = try #require(GeneratedPayloads.payload(for: .recall(recall), unit: "u02", display: { _ in nil }))
        #expect(p.format == .recall && p.targets.first?.skill == .recall)
        #expect(ExerciseHostModel.make(p, env: .preview(), sink: nil) != nil)
        let read = GeneratedReadCard(
            exerciseId: "gen:read:w:caffe", itemId: "w:caffe", promptIt: "il caffè",
            options: ["coffee", "tea", "milk"], answer: 0)
        let q = try #require(GeneratedPayloads.payload(for: .read(read), unit: "u02", display: { _ in nil }))
        guard case .choice(let m)? = ExerciseHostModel.make(q, env: .preview(), sink: nil) else {
            Issue.record("expected a choice")
            return
        }
        #expect(m.options.count == 3 && m.correctIndex == 0)
    }

    @Test func nextReviewTexts() {
        let today: Int64 = 20_000
        func due(_ days: Int64) -> Int64 { LocalDay.startMs(dayNumber: today + days, tzOffsetMinutes: 120) + 3_600_000 }
        #expect(WordsCopy.nextReviewText(dueMs: due(-3), today: today, tzOffsetMinutes: 120) == "Today")
        #expect(WordsCopy.nextReviewText(dueMs: due(0), today: today, tzOffsetMinutes: 120) == "Today")
        #expect(WordsCopy.nextReviewText(dueMs: due(1), today: today, tzOffsetMinutes: 120) == "Tomorrow")
        #expect(WordsCopy.nextReviewText(dueMs: due(9), today: today, tzOffsetMinutes: 120) == "In 9 days")
        #expect(WordsCopy.nextReviewText(dueMs: due(15), today: today, tzOffsetMinutes: 120) == "In 2 weeks")
        #expect(WordsCopy.subtitle(count: 64) == "64 words · how well you know each one, skill by skill")
    }

    /// Gives some answer to any exercise so an attempt is recorded.
    private func answerSomehow(_ host: ExerciseHostModel) {
        switch host {
        case .typed(let m):
            m.response = "boh"
            m.check()
            m.showAnswer()
        case .choice(let m):
            m.select(m.correctIndex)
        case .match(let m):
            for i in 0..<m.pairs.count {
                m.tapLeft(i)
                m.tapRight(i)
            }
        case .building(let m):
            m.showAnswer()
        default:
            break
        }
    }
}
