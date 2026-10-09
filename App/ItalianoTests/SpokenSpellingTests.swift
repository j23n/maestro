import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// Spoken spelling (CL25, docs/05 § Speech transcripts): a recogniser writes a spelled name as letters (*M A R C O*),
/// so every speaking format grades with the pack's letter names from its environment (`ExerciseEnvironment
/// .letterNames`, loaded by `AppModel` from `PackReader.letterNames()`). The example payloads are edited to ask for a
/// spelling.
@MainActor
@Suite struct SpokenSpellingTests {
    let sink = RecordingAttemptSink()

    /// The Unit 0 letter items' names as the pack carries them (`fixtures/grading/transcripts.json`).
    static func letters() throws -> LetterNames {
        let url = PayloadFixtures.repoRoot.appendingPathComponent("fixtures/grading/transcripts.json")
        let doc = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        return LetterNames(try #require(doc["letterNames"] as? [String: String]))
    }

    /// A pattern as payloads carry it (the expansions are only the answer key; graders parse the source).
    static func pattern(_ source: String, spelling: [String: String]? = nil) -> [String: Any] {
        var out: [String: Any] = ["source": source, "expansions": [Normalizer.normalize(source)]]
        if let spelling {
            out["spelling"] = spelling.keys.sorted().map { ["name": $0, "letter": spelling[$0] ?? ""] }
        }
        return out
    }

    /// An example exercise with some of its JSON replaced.
    static func exercise(_ id: String, _ edit: (inout [String: Any]) throws -> Void) throws -> ExercisePayload {
        let url = PayloadFixtures.repoRoot.appendingPathComponent("fixtures/packs/payload-examples.json")
        let doc = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        let list = try #require(doc["exercises"] as? [[String: Any]])
        var raw = try #require(list.first { $0["id"] as? String == id })
        try edit(&raw)
        return try JSONDecoder().decode(ExercisePayload.self, from: JSONSerialization.data(withJSONObject: raw))
    }

    func env(_ letters: LetterNames) -> ExerciseEnvironment {
        var e = ExerciseEnvironment.preview()
        e.canSpeak = true
        e.letterNames = letters
        return e
    }

    static let marco = "emme, a, erre, ci, o"
    static let spell =
        "{bi|ci|di|effe|gi|acca|i lunga|cappa|elle|emme|enne|pi|cu|erre|esse|ti|vu|doppia vu|ics|ipsilon|zeta}"

    @Test func talkFindsTheSpellPoint() throws {
        let payload = try Self.exercise("u02.task.talk") { raw in
            var points = try #require(raw["points"] as? [[String: Any]])
            points[1] = ["id": "spell", "en": "Spell your name", "accept": [Self.pattern(Self.spell)]]
            raw["points"] = points
        }
        let heard = SpeechResult(transcript: "Buongiorno! Marco: M A R C O.", alternatives: [], confidence: nil)
        let spelled = try #require(TalkModel(payload: payload, env: env(try Self.letters()), sink: sink))
        spelled.submitSpoken(heard)
        #expect(spelled.found == ["greet", "spell"])
        let unmapped = try #require(TalkModel(payload: payload, env: env(.empty), sink: sink))
        unmapped.submitSpoken(heard)
        #expect(unmapped.found == ["greet"])
    }

    @Test func aConversationTurnHearsTheSpelling() throws {
        let payload = try Self.exercise("u02.l1.ex25") { raw in
            var nodes = try #require(raw["nodes"] as? [[String: Any]])
            var expect = try #require(nodes[0]["expect"] as? [[String: Any]])
            expect[0]["accept"] = [Self.pattern(Self.marco)]
            nodes[0]["expect"] = expect
            raw["nodes"] = nodes
        }
        let heard = SpeechResult(transcript: "M-A-R-C-O", alternatives: [], confidence: nil)
        let spelled = try #require(ConversationModel(payload: payload, env: env(try Self.letters()), sink: sink))
        spelled.submitSpoken(heard)
        #expect(spelled.nodeID == "n3")
        let unmapped = try #require(ConversationModel(payload: payload, env: env(.empty), sink: sink))
        unmapped.submitSpoken(heard)
        #expect(unmapped.nodeID == "n1")
    }

    @Test func repeatAfterMeHearsTheSpelling() throws {
        let payload = try Self.exercise("u02.l1.ex14") { raw in raw["accept"] = Self.pattern(Self.marco) }
        let heard = SpeechResult(transcript: "m. a. r. c. o.", alternatives: [], confidence: nil)
        let spelled = try #require(RepeatModel(payload: payload, env: env(try Self.letters()), sink: sink))
        spelled.submit(heard)
        #expect(spelled.passed == true && spelled.heard == "m. a. r. c. o.")
        let unmapped = try #require(RepeatModel(payload: payload, env: env(.empty), sink: sink))
        unmapped.submit(heard)
        #expect(unmapped.passed == false)
    }

    @Test func sayItHearsTheSpelling() throws {
        let payload = try Self.exercise("u02.l1.ex04") { raw in
            raw["answer"] = Self.pattern("elle, u, ci, a")
            raw["near"] = [Any]()
        }
        let task = try #require(TypedTask(payload: payload))
        let heard = SpeechResult(transcript: "L U C A", alternatives: [], confidence: nil)
        let spelled = TypedExerciseModel(task: task, env: env(try Self.letters()), sink: sink)
        spelled.submitSpoken(heard)
        let unmapped = TypedExerciseModel(task: task, env: env(.empty), sink: sink)
        unmapped.submitSpoken(heard)
        #expect(sink.drafts.map(\.outcome) == [.correct, .wrong])
        #expect(sink.drafts.allSatisfy { $0.mode == .spoken })
    }

    /// CL40: a recall that spells, as the pack gives it (`spelling`), is right only letter for letter when spoken.
    @Test func aSpokenSpellingIsRightOnlyLetterForLetter() throws {
        let payload = try Self.exercise("u02.l1.ex04") { raw in
            raw["answer"] = Self.pattern("elle, u, ci, a", spelling: ["elle": "L", "u": "U", "ci": "C", "a": "A"])
            raw["near"] = [Any]()
        }
        let task = try #require(TypedTask(payload: payload))
        for transcript in ["L U C O", "L U C A"] {
            let model = TypedExerciseModel(task: task, env: env(try Self.letters()), sink: sink)
            model.submitSpoken(SpeechResult(transcript: transcript, alternatives: [], confidence: nil))
        }
        #expect(sink.drafts.map(\.outcome) == [.wrong, .correct])
    }

    /// AppModel reads the names from the pack and hands them to every player it launches. (The mini pack, built from
    /// the frozen seed course, has no letter items; Storage's tests read a pack that has them.)
    @Test func theAppPassesThePacksNamesToItsPlayers() async throws {
        let folder = FileManager.default.temporaryDirectory
            .appendingPathComponent("italiano-spelling-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let app = AppModel(
            env: .init(
                packURL: PackAdaptersTests.packURL, learnerURL: folder.appendingPathComponent("learner.sqlite"),
                clock: FixedClock(ms: 1_791_271_800_000, tzOffsetMinutes: 120), ids: SeededUUIDSource(seed: "s"),
                platform: .iPhone))
        await app.start()
        #expect(app.phase == .ready)
        let fromPack = try await PackReader.open(url: PackAdaptersTests.packURL).letterNames()
        #expect(app.letterNames == fromPack)
        let launch = try #require(try await app.launch(step: "u02.l1.step-preview"))
        #expect(launch.environment.letterNames == app.letterNames)
    }
}
