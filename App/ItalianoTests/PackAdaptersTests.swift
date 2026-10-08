import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// The App's view-model inputs built from the committed mini pack (`fixtures/packs/mini.sqlite`, Unit 2's golden
/// lesson): the path a real launch takes, minus the UI.
@MainActor
@Suite struct PackAdaptersTests {
    static let packURL = PayloadFixtures.repoRoot.appendingPathComponent("fixtures/packs/mini.sqlite")

    func reader() async throws -> PackReader { try await PackReader.open(url: Self.packURL) }

    @Test func courseOutlineFromThePack() async throws {
        let outline = CourseOutline(try await reader().courseOutline())
        #expect(outline.units.map(\.number) == [0, 1, 2])
        let u02 = try #require(outline.unit("u02"))
        #expect(u02.lessons.map(\.id) == ["u02.l1"])
        #expect(u02.lessons[0].steps.first?.kind == .preview)
        #expect(u02.unitSteps.first?.kind == .opener && u02.unitSteps.contains { $0.kind == .check })
        #expect(!u02.canDos.isEmpty && u02.summaryEn != nil)
    }

    @Test func theGoldenLessonPlaysFromThePack() async throws {
        let bundle = try await LessonLoader.bundle(for: "u02.l1.step-story", reader: reader())
        #expect(bundle.lessonID == "u02.l1" && bundle.steps.first?.id == "u02.l1.step-preview")
        #expect(bundle.steps.map(\.title).contains("Unit 2 · Story"))
        let player = LessonPlayerModel(bundle: bundle)
        #expect(player.exerciseTotal > 10)
        // Every page has its content, and every exercise gets a view model.
        for entry in player.entries {
            switch entry.page {
            case .exercise(let id):
                let payload = try #require(bundle.exercises[id], "missing \(id)")
                #expect(ExerciseHostModel.make(payload, env: .preview(), sink: nil) != nil, "\(id)")
            case .story(let t), .reading(let t), .transcript(let t), .listening(let t, _):
                #expect(bundle.texts[t] != nil, "missing text \(t)")
            case .note(let n):
                #expect(bundle.notes[n] != nil, "missing note \(n)")
            case .meet(let items):
                #expect(items.allSatisfy { bundle.items[$0] != nil })
            default:
                break
            }
        }
        // Story taps find their glosses, and the story has new words.
        let story = try #require(bundle.texts["u02.l1.story"])
        let line = try #require(story.lines.first { $0.text.tokens.contains { $0.kind == .word && $0.itemId != nil } })
        let token = try #require(line.text.tokens.firstIndex { $0.kind == .word && $0.itemId != nil })
        #expect(bundle.gloss(text: story.id, line: line.number, token: token) != nil)
        #expect(!bundle.newWords(in: story.id).isEmpty)
        #expect(!bundle.characters.isEmpty)
    }

    @Test func unitLevelStepsOpenOnTheirOwn() async throws {
        let bundle = try await LessonLoader.bundle(for: "u02.step-conversation-1", reader: reader())
        #expect(bundle.steps.map(\.id) == ["u02.step-conversation-1"])
        let player = LessonPlayerModel(bundle: bundle)
        let exercise = try #require(player.currentExercise)
        guard case .conversation(let c)? = ExerciseHostModel.make(exercise, env: .preview(), sink: nil) else {
            Issue.record("expected a conversation")
            return
        }
        #expect(bundle.characters[c.conversation.with] != nil)
    }
}
