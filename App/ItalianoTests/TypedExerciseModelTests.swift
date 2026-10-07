import Foundation
import LearningCore
import Testing

@testable import Italiano

/// Loads fixtures/packs/payload-examples.json from the repo (tests run from any working directory).
enum PayloadFixtures {
    static let repoRoot: URL = {
        // scripts/check-app-logic.sh compiles symlinks elsewhere and sets ITALIANO_ROOT; Xcode uses #filePath.
        if let root = ProcessInfo.processInfo.environment["ITALIANO_ROOT"] { return URL(fileURLWithPath: root) }
        var url = URL(fileURLWithPath: #filePath)
        for _ in 0..<3 { url.deleteLastPathComponent() }  // App/ItalianoTests/<file> → repo root
        return url
    }()

    static func exercise(_ id: String) throws -> ExercisePayload {
        let data = try Data(contentsOf: repoRoot.appendingPathComponent("fixtures/packs/payload-examples.json"))
        let doc = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        let list = try #require(doc["exercises"] as? [[String: Any]])
        let raw = try #require(list.first { $0["id"] as? String == id })
        return try JSONDecoder().decode(ExercisePayload.self, from: JSONSerialization.data(withJSONObject: raw))
    }

    /// Every example exercise, by ID.
    static func exercises() throws -> [ExerciseID: ExercisePayload] {
        let data = try Data(contentsOf: repoRoot.appendingPathComponent("fixtures/packs/payload-examples.json"))
        let doc = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        let list = try #require(doc["exercises"] as? [[String: Any]])
        var out: [ExerciseID: ExercisePayload] = [:]
        for raw in list {
            let p = try JSONDecoder().decode(ExercisePayload.self, from: JSONSerialization.data(withJSONObject: raw))
            out[p.id] = p
        }
        return out
    }

    /// The example step payloads, in file order (they carry no IDs; tests name them).
    static func steps() throws -> [StepPayload] {
        let data = try Data(contentsOf: repoRoot.appendingPathComponent("fixtures/packs/payload-examples.json"))
        let doc = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        let list = try #require(doc["steps"] as? [[String: Any]])
        return try list.map {
            try JSONDecoder().decode(StepPayload.self, from: JSONSerialization.data(withJSONObject: $0))
        }
    }
}

@MainActor
@Suite struct TypedExerciseModelTests {
    func model(_ id: String, context: AttemptContext = .lesson, canSpeak: Bool = false) throws
        -> (TypedExerciseModel, RecordingAttemptSink)
    {
        let sink = RecordingAttemptSink()
        var env = ExerciseEnvironment.preview(context: context)
        env.canSpeak = canSpeak
        let task = try #require(TypedTask(payload: try PayloadFixtures.exercise(id)))
        return (TypedExerciseModel(task: task, env: env, sink: sink), sink)
    }

    @Test func rightFirstTimeRecordsOneAttemptForEveryTarget() throws {
        let (m, sink) = try model("u02.l1.ex01")
        m.response = "un"
        m.check()
        #expect(m.isDone)
        #expect(m.feedback?.tone == .success)
        let d = try #require(sink.drafts.first)
        #expect(sink.drafts.count == 1)
        #expect(d.attemptIndex == 1 && d.outcome == .correct && d.feedbackShown == .none && d.mode == .typed)
        #expect(d.targets.map(\.itemID) == ["g:indefinite-article", "g:noun-gender"])
        #expect(d.response == "un")
    }

    @Test func nearMissShowsItsHintThenTheSecondAttemptCounts() throws {
        let (m, sink) = try model("u02.l1.ex01")
        m.response = "una"
        m.check()
        #expect(m.feedback?.headline == "Not quite.")
        #expect(m.feedback?.detail == "Una is for feminine nouns. Is cappuccino masculine or feminine?")
        #expect(m.feedback?.canTryAgain == true)
        m.tryAgain()
        #expect(m.response.isEmpty)
        m.response = "un"
        m.check()
        #expect(m.isDone)
        #expect(sink.drafts.map(\.attemptIndex) == [1, 2])
        #expect(sink.drafts.map(\.outcome) == [.wrong, .correct])
        #expect(sink.drafts[1].feedbackShown == .hint)
    }

    @Test func almostOnARecallShowsTheCorrection() throws {
        let (m, sink) = try model("u02.l1.ex04")
        m.response = "una cornetto"
        m.check()
        #expect(m.isDone)
        #expect(sink.drafts.first?.outcome == .almost)
        #expect(m.feedback?.tone == .success)
    }

    @Test func showAnswerRevealsTheModelAnswerAndRule() throws {
        let (m, sink) = try model("u02.l1.ex01")
        m.response = "il"
        m.check()
        m.showAnswer()
        #expect(m.feedback?.answer == "un")
        #expect(m.feedback?.rule == "un with most masculine nouns, una with feminine nouns (un' before a vowel).")
        #expect(sink.drafts.last?.outcome == .revealed && sink.drafts.last?.feedbackShown == .answer)
        m.acknowledge()
        #expect(m.isDone)
    }

    @Test func checksAllowOneAttemptAndNoHints() throws {
        let (m, sink) = try model("u02.l1.ex01", context: .check)
        #expect(!m.canRequestHint)
        m.response = "una"
        m.check()
        #expect(m.isDone)
        #expect(m.feedback == nil)  // no feedback until the end of the check
        #expect(sink.drafts.count == 1 && sink.drafts[0].outcome == .wrong)
    }

    @Test func sayItGradesTheTranscriptUnderSpeak() throws {
        let (m, sink) = try model("u02.l1.ex04", canSpeak: true)
        #expect(m.canSayIt)
        m.submitSpoken(SpeechResult(transcript: "Un cornetto", alternatives: [], confidence: 0.9))
        let d = try #require(sink.drafts.first)
        #expect(d.mode == .spoken && d.outcome == .correct)
        #expect(d.targets.first?.skill == .speak)
        #expect(RatingPolicy.rating(format: d.format, outcome: .wrong, mode: d.mode, attemptIndex: 1, context: .lesson)
            == nil)  // a failed spoken answer never becomes a lapse
    }

    @Test func clozeHasNoSayIt() throws {
        let (m, _) = try model("u02.l1.ex01", canSpeak: true)
        #expect(!m.canSayIt)
    }
}
