import Foundation
import LearningCore
import Testing

@testable import Italiano

@MainActor
@Suite struct LessonPlayerModelTests {
    /// opener, preview, story, note, practice, sounds, use — the lesson-shaped examples, named s0…s6.
    func bundle() throws -> LessonBundle {
        let kinds: Set<StepKind> = [.opener, .preview, .story, .note, .practice, .sounds, .use]
        let steps = try PayloadFixtures.steps().filter { kinds.contains($0.kind) }
        return LessonBundle(
            lessonID: "u02.l1", unitID: "u02", title: "Al bar",
            steps: steps.enumerated().map {
                .init(id: StepID(rawValue: "s\($0.offset)"), title: "Step", payload: $0.element)
            },
            exercises: try PayloadFixtures.exercises())
    }

    @Test func stepsFlattenIntoPagesAndExercisesCount() throws {
        let m = LessonPlayerModel(bundle: try bundle())
        #expect(m.entries.first?.page == .opener("u02"))
        #expect(m.entries[1].page == .meet(["w:caffe", "c:vorrei"]))
        #expect(m.entries[5].page == .story("u02.l1.story"))
        #expect(m.exerciseTotal == 14)  // 3 preview + 3 questions + 4 practice + 3 sounds + 1 use
        #expect(m.exerciseNumber == 0 && m.progress == 0)
        m.advance()
        m.advance()
        #expect(m.exerciseNumber == 1 && m.currentExercise == nil)  // the preview match isn't in the examples
        let practice = m.entries.compactMap { e -> ExerciseID? in
            guard e.stepIndex == 4, case .exercise(let id) = e.page else { return nil }
            return id
        }
        #expect(Array(practice.prefix(2)) == ["u02.l1.ex01", "u02.l1.ex04"])  // the block first, then the mix
        #expect(Set(practice.suffix(2)) == ["u02.l1.ex15", "u02.l1.ex17"])
    }

    @Test func resumeOpensAnUnstartedStepAtItsFirstPage() throws {
        let preview: Set<ExerciseID> = ["u02.l1.step-preview.b1.match", "u02.l1.step-preview.b1.w-caffe",
                                        "u02.l1.step-preview.b1.c-vorrei"]
        let fresh = LessonPlayerModel(bundle: try bundle(), answered: preview)
        #expect(fresh.current?.page == .story("u02.l1.story"))  // read the story before its questions
        #expect(fresh.exerciseNumber == 3)
        let midStep = LessonPlayerModel(bundle: try bundle(), answered: preview.union(["u02.l1.q1"]))
        #expect(midStep.current?.page == .exercise("u02.l1.q2"))
        #expect(midStep.exerciseNumber == 5)
    }

    @Test func everythingAnsweredMeansFinished() throws {
        let b = try bundle()
        let all = Set(LessonPlayerModel.flatten(b).compactMap { e -> ExerciseID? in
            if case .exercise(let id) = e.page { id } else { nil }
        })
        let m = LessonPlayerModel(bundle: b, answered: all)
        #expect(m.isFinished && m.current == nil && m.progress == 1 && m.exerciseNumber == 14)
        m.advance()
        #expect(m.isFinished)
    }

    @Test func checksGetASectionPageBeforeTheirExercises() throws {
        let check = try #require(try PayloadFixtures.steps().first { $0.kind == .check })
        let b = LessonBundle(lessonID: "u02.check", unitID: "u02", title: "Check",
                             steps: [.init(id: "u02.check", title: "Unit 2 · Check", payload: check)], exercises: [:])
        let pages = LessonPlayerModel.flatten(b).map(\.page)
        #expect(pages == [.checkSection(id: "listening", title: "Listening"), .exercise("u02.check.01"),
                          .exercise("u02.check.02")])
    }

    @Test func everyExampleExerciseGetsAViewModel() throws {
        for (id, payload) in try PayloadFixtures.exercises() {
            let host = ExerciseHostModel.make(payload, env: .preview(), sink: nil)
            #expect(host != nil, "\(id)")
            #expect(host?.isDone == false, "\(id)")
        }
    }
}
