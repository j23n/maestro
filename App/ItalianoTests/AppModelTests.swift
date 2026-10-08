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

        // Relaunch: the same database, a fresh model; the lesson resumes after what was answered.
        let again = model("b")
        await again.start()
        let resumed = try #require(try await again.launch(step: "u02.l1.step-preview"))
        #expect(resumed.model.exerciseNumber >= 2)
        #expect(again.today?.continueCard?.unitID == "u02")
    }

    @Test func aMissingPackFailsToLaunch() async {
        let app = AppModel(env: .init(
            packURL: folder.appendingPathComponent("nope.sqlite"), learnerURL: folder.appendingPathComponent("l.sqlite"),
            clock: clock, ids: SeededUUIDSource(seed: "c"), platform: .Mac))
        await app.start()
        guard case .failed = app.phase else {
            Issue.record("expected a launch failure, got \(app.phase)")
            return
        }
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
