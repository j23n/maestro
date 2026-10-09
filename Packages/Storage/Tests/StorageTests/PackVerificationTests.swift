import Foundation
import GRDB
import LearningCore
import Testing

@testable import Storage

/// M2.11: every payload of a pack decodes through the reader and every ID a payload names exists. The test pack
/// always runs; `fixtures/packs/mini.sqlite` (the pack builder's output, M1.10) runs once it exists.
@Suite struct PackVerificationTests {
    @Test func theTestPackIsClean() async throws {
        let reader = try PackReader(url: try TestPack.build())
        let report = try await reader.verify()
        #expect(report.problems == [])
        #expect(report.isClean)
        #expect(report.decoded["steps"] == 15)
        #expect(report.decoded["exercises"] == TestPack.allExercisePayloads.count)
        #expect(report.decoded["grammar_notes"] == 1 && report.decoded["assessments"] == 2)
        #expect(report.decoded["texts"] == 5 && report.decoded["items"] == 12)
        #expect(report.decoded["sounds"] == 1 && report.decoded["countries"] == 2)
        #expect(report.decoded["letters"] == 0)
    }

    @Test func problemsAreCollectedNotThrown() async throws {
        let reader = try PackReader(url: try TestPack.build { db in
            try db.execute(sql: "UPDATE exercises SET payload = '[]' WHERE id = 'u02.l1.ex13'")
            try db.execute(sql: "UPDATE grammar_notes SET body = json_set(body, '$.grammar', json('[]'))")
            try db.execute(sql: "UPDATE texts SET layout = '{\"type\": \"brochure\"}' WHERE id = 'u02.task.menu'")
            try db.execute(sql: "UPDATE countries SET alt_home_phrases_it = 'in America' WHERE id = 'us'")
            try db.execute(sql: "DELETE FROM exercise_targets WHERE exercise_id = 'u02.l1.ex04'")
            try db.execute(sql: """
                UPDATE steps SET payload = json_set(payload, '$.questionIds[1]', 'u02.l1.q9', \
                '$.textId', 'u02.l1.gone') WHERE id = 'u02.l1.step-story'
                """)
        })
        let report = try await reader.verify()
        #expect(!report.isClean)
        let ids = Set(report.problems.compactMap { problem -> String? in
            guard case .malformedRow(let table, let id, _) = problem else { return nil }
            return "\(table) \(id)"
        })
        #expect(ids == [
            "exercises u02.l1.ex13", "grammar_notes u02.l1.note", "texts u02.task.menu", "countries us",
            "exercises u02.l1.ex04", "steps u02.l1.step-story",
        ])
        #expect(report.problems.contains(
            .malformedRow(table: "steps", id: "u02.l1.step-story", reason: "names a missing exercise u02.l1.q9")))
        #expect(report.problems.contains(
            .malformedRow(table: "steps", id: "u02.l1.step-story", reason: "names a missing text u02.l1.gone")))
        #expect(report.decoded["exercises"] == TestPack.allExercisePayloads.count - 2)
    }

    /// The pack builder's mini pack (Unit 2 Lesson 1 with its task and check): every payload decodes, every
    /// reference resolves, the engine's index builds, and every step's exercises and texts load.
    @Test(.enabled(if: FileManager.default.fileExists(atPath: Repo.url("fixtures/packs/mini.sqlite").path)))
    func theMiniPackDecodesThroughTheReader() async throws {
        let reader = try PackReader(url: Repo.url("fixtures/packs/mini.sqlite"))
        let report = try await reader.verify()
        #expect(report.problems == [])
        #expect((report.decoded["steps"] ?? 0) > 0 && (report.decoded["exercises"] ?? 0) > 0)
        let index = try await reader.contentIndex()
        for step in try await reader.steps() {
            let exercises = try await reader.exercises(forStep: step.id)
            #expect(exercises.map(\.id) == index.step(step.id)?.presentationOrder)
            _ = try await reader.texts(step.textIds)
        }
        _ = try await reader.allItems()
        _ = try await reader.knownForms()
        _ = try await reader.audioCatalog()
        _ = try await reader.searchIndex()
    }
}
