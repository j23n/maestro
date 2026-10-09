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

    /// The Unit 0 letter items' names as the pack carries them (`fixtures/grading/transcripts.json`), with the letters
    /// whose names are also words.
    static func letters() throws -> LetterNames {
        let url = PayloadFixtures.repoRoot.appendingPathComponent("fixtures/grading/transcripts.json")
        let doc = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        return LetterNames(
            try #require(doc["letterNames"] as? [String: String]),
            alsoWords: Set(try #require(doc["alsoWords"] as? [String])))
    }

    /// A pattern as payloads carry it (the expansions are only the answer key; graders parse the source): `spelling`
    /// maps each name to its letter, nil for *doppia*, which the payload writes as null (CL40).
    static func pattern(_ source: String, spelling: [String: String?]? = nil) -> [String: Any] {
        var out: [String: Any] = ["source": source, "expansions": [Normalizer.normalize(source)], "spelling": NSNull()]
        if let spelling {
            out["spelling"] = spelling.keys.sorted().map { name -> [String: Any] in
                ["name": name, "letter": spelling[name].flatMap { $0 } ?? NSNull()]
            }
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

    /// CL40 on the payload example that spells (Unit 0's Rossi, as the pack builds it): *doppia*'s letter is null, and
    /// a double letter may be said either way, but a missing one fails.
    @Test func theSpelledExampleIsRightOnlyLetterForLetter() throws {
        let payload = try Self.exercise("u00.l3.ex22") { _ in }
        guard case .recall(let recall) = payload.body else {
            Issue.record("u00.l3.ex22 is a recall")
            return
        }
        #expect(recall.answer.spelling?.first == SpellingName(name: "doppia", letter: nil))
        let task = try #require(TypedTask(payload: payload))
        for transcript in ["R O S S I", "erre o doppia S i", "R O S I", "R O S S I S"] {
            let model = TypedExerciseModel(task: task, env: env(try Self.letters()), sink: sink)
            model.submitSpoken(SpeechResult(transcript: transcript, alternatives: [], confidence: nil))
        }
        #expect(sink.drafts.map(\.outcome) == [.correct, .correct, .wrong, .wrong])
        // Spelled with the doubling word as the pattern names it, through the edited payload too.
        let edited = try Self.exercise("u02.l1.ex04") { raw in
            raw["answer"] = Self.pattern(
                "erre, o, doppia esse, i", spelling: ["erre": "R", "o": "O", "doppia": nil, "esse": "S", "i": "I"])
            raw["near"] = [Any]()
        }
        guard case .recall(let body) = edited.body else { return }
        #expect(body.answer.spelling == recall.answer.spelling)
    }

    /// AppModel reads the names from the pack and hands the same table to every player it launches: a lesson, a
    /// review, placement and the final check. `fixtures/packs/assessment.sqlite` is the mini pack (whose frozen seed
    /// course has no letter items) plus two letter items, `c:doppia` and the assessments placement and the final check
    /// need (`itcontent.pack.assessment_fixture`).
    @Test func theAppPassesThePacksNamesToItsPlayers() async throws {
        let folder = FileManager.default.temporaryDirectory
            .appendingPathComponent("italiano-spelling-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let pack = AssessmentContainerTests.packURL
        let app = AppModel(
            env: .init(
                packURL: pack, learnerURL: folder.appendingPathComponent("learner.sqlite"),
                clock: FixedClock(ms: 1_791_271_800_000, tzOffsetMinutes: 120), ids: SeededUUIDSource(seed: "s"),
                platform: .iPhone))
        await app.start()
        try #require(app.phase == .ready)
        let names = app.letterNames
        #expect(names.count == 2 && names.name(of: "M") == ["emme"] && names.name(of: "S") == ["esse"])
        #expect(names.doubling == ["doppia"])
        #expect(names == (try await PackReader.open(url: pack).letterNames()))

        let lesson = try #require(try await app.launch(step: "u02.l1.step-preview"))
        #expect(lesson.environment.letterNames == names)
        app.completeOnboarding(
            .init(reason: nil, name: "", forms: .both, country: nil, goal: 5, beginner: false, consent: nil))
        let placement = try #require(try await app.startPlacement())
        #expect(placement.model.env.letterNames == names)
        // Placed in Unit 2 (Unit 1's block right, Unit 2's wrong), the skipped units' words wait for review.
        placement.model.start()
        while placement.model.phase == .playing {
            guard case .choice(let m) = placement.model.host else {
                Issue.record("placement items are choice questions here")
                return
            }
            let right = placement.model.session.results.isEmpty || placement.model.session.position == 0
            m.select(right ? m.correctIndex : (m.correctIndex + 1) % m.options.count)
            placement.model.advance()
        }
        app.finishPlacement(try #require(placement.model.completion), launch: placement, activeSeconds: 60)
        await app.settle()
        let review = try #require(try await app.startReview())
        #expect(review.model.env.letterNames == names)
        let final = try #require(try await app.startFinalCheck())
        #expect(final.model.env.letterNames == names)
    }
}
