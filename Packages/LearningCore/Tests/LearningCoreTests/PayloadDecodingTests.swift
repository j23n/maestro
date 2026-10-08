import Foundation
import Testing

@testable import LearningCore

/// M2.1: every payload in fixtures/packs/payload-examples.json (and, once the pack builder writes it,
/// fixtures/packs/mini-payloads.json) decodes; unknown keys are ignored; a missing required key fails.
@Suite struct PayloadDecodingTests {
    static func examples() throws -> [String: Any] {
        try #require(Fixtures.json("fixtures/packs/payload-examples.json") as? [String: Any])
    }

    static func data(_ object: Any) throws -> Data { try JSONSerialization.data(withJSONObject: object) }

    @Test func everyExampleExerciseDecodes() throws {
        let list = try #require(Self.examples()["exercises"] as? [[String: Any]])
        var formats = Set<ExerciseFormat>()
        for raw in list {
            let p = try JSONDecoder().decode(ExercisePayload.self, from: Self.data(raw))
            formats.insert(p.format)
            switch (p.format, p.body) {
            case (.cloze, .cloze(let c)):
                #expect(try c.gapPattern().expansions(profile: .unspecified).first?.text == "un")
                #expect(c.before.rebuilt == c.before.text && c.after.rebuilt == c.after.text)
            case (.recall, .recall(let r)):
                #expect(try r.answer.parsed().firstExpansion(profile: .unspecified)?.text == "un cornetto")
            case (.sentenceBuilding, .sentenceBuilding(let s)):
                let order = s.shuffledTiles(exerciseID: p.id)
                #expect(order.sorted() == (s.tiles + s.distractors).sorted())
                #expect(!s.answers.contains(order.joined(separator: " ")))
            case (.soundPair, .soundPair(let sp)):
                #expect(sp.question == .whichWord ? sp.play == 1 : sp.answer == .double)
            case (.choice, .choice(let c)):
                #expect(c.displayOrder(exerciseID: p.id).sorted() == Array(c.options.indices))
            case (.conversation, .conversation(let conv)):
                #expect(conv.node(conv.start)?.expect.first?.next == "n3")
                #expect(conv.nodes.last?.final == true)
                #expect(conv.register(at: "n3", path: ["n1"]) == .lei)
            case (.talk, .talk(let t)): #expect(try t.points.map { try $0.matcherPoint() }.count == 2)
            case (.relay, .relay(let r)): #expect(r.answerEn.graderAnswer == .price(1.6))
            case (.writing, .writing(let w)): #expect(w.kind == .form && w.fields?.count == 2)
            case (.dictation, .dictation), (.repeat, .repeat), (.trueFalse, .trueFalse), (.match, .match): break
            default: Issue.record("\(p.id): body \(p.body) doesn't match format \(p.format)")
            }
        }
        #expect(formats == Set(ExerciseFormat.allCases))
    }

    @Test func nearMissesBecomeGraderInput() throws {
        let list = try #require(Self.examples()["exercises"] as? [[String: Any]])
        let recall = try JSONDecoder().decode(ExercisePayload.self, from: Self.data(list[1]))
        let near = recall.nearMisses()
        #expect(near.count == 1 && near[0].outcome == .almost)
        guard case .recall(let body) = recall.body else { return }
        let grade = TypedAnswerGrader().grade("una cornetto", accepted: try body.answer.parsed(), near: near)
        #expect(grade.outcome == .almost)
        #expect(grade.nearHint == "Cornetto is masculine.")
    }

    /// Generated preview recalls carry the bare noun as a `correctWithNote` near-miss (docs/05, docs/06 § 1).
    @Test func aCorrectWithNoteNearMissKeepsItsOutcome() throws {
        let json = #"""
            {"answer": {"source": "cornetto", "expansions": ["cornetto"]}, "outcome": "correctWithNote",
             "hint": "Say it with its article: il cornetto"}
            """#
        let near = try JSONDecoder().decode(NearPayload.self, from: Data(json.utf8))
        let miss = try near.nearMiss()
        #expect(miss.outcome == .correctWithNote)
        let grade = TypedAnswerGrader().grade(
            "cornetto", accepted: try AnswerPattern("{il|un} [cornetto]"), near: [miss])
        #expect(grade.outcome == .correctWithNote)
        #expect(grade.nearHint == "Say it with its article: il cornetto")
    }

    @Test func everyStepNoteAssessmentAndLayoutDecodes() throws {
        let ex = try Self.examples()
        let steps = try #require(ex["steps"] as? [[String: Any]])
        let decoded = try steps.map { try JSONDecoder().decode(StepPayload.self, from: Self.data($0)) }
        #expect(
            Set(decoded.map(\.kind)).isSuperset(of: [.opener, .preview, .story, .note, .practice, .check, .fluency]))
        let practice = try #require(decoded.first { $0.kind == .practice })
        let order = practice.exerciseOrder(stepID: "u02.l1.step-practice")
        #expect(Array(order.prefix(2)) == ["u02.l1.ex01", "u02.l1.ex04"])  // block first, in file order
        #expect(Set(order.suffix(2)) == ["u02.l1.ex15", "u02.l1.ex17"])
        #expect(order == practice.exerciseOrder(stepID: "u02.l1.step-practice"))  // the same on every device
        let note = try JSONDecoder().decode(
            NoteBody.self, from: Self.data(try #require((ex["notes"] as? [Any])?.first)))
        #expect(note.blocks.count == 4)
        if case .examples(let e) = note.blocks[2] { #expect(e[0].highlight == [3]) } else { Issue.record("examples") }
        for raw in try #require(ex["assessments"] as? [Any]) {
            _ = try JSONDecoder().decode(AssessmentPayload.self, from: Self.data(raw))
        }
        let layout = try JSONDecoder().decode(
            LayoutPayload.self, from: Self.data(try #require((ex["layouts"] as? [Any])?.first)))
        guard case .menu(_, let sections) = layout else {
            Issue.record("menu")
            return
        }
        #expect(sections[0].title == .plain("Caffetteria"))
        #expect(sections[0].rows[0].price == .plain("1,20"))
    }

    @Test func unknownKeysAreIgnoredAndMissingRequiredKeysFail() throws {
        let list = try #require(Self.examples()["exercises"] as? [[String: Any]])
        var extra = list[0]
        extra["someFutureKey"] = ["anything": 1]
        #expect(throws: Never.self) { try JSONDecoder().decode(ExercisePayload.self, from: Self.data(extra)) }
        var missing = list[0]
        missing.removeValue(forKey: "gap")
        #expect(throws: DecodingError.self) { try JSONDecoder().decode(ExercisePayload.self, from: Self.data(missing)) }
        var noTargets = list[1]
        noTargets.removeValue(forKey: "targets")
        #expect(throws: DecodingError.self) {
            try JSONDecoder().decode(ExercisePayload.self, from: Self.data(noTargets))
        }
    }

    @Test func payloadsRoundTrip() throws {
        let list = try #require(Self.examples()["exercises"] as? [[String: Any]])
        for raw in list {
            let p = try JSONDecoder().decode(ExercisePayload.self, from: Self.data(raw))
            let again = try JSONDecoder().decode(ExercisePayload.self, from: JSONEncoder().encode(p))
            #expect(again == p)
        }
    }

    /// The pack builder's output (M1.10): every payload of the golden lesson, task and check decodes.
    @Test func miniPayloadsDecodeWhenPresent() throws {
        let url = Fixtures.url("fixtures/packs/mini-payloads.json")
        guard FileManager.default.fileExists(atPath: url.path) else { return }
        let doc = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        for (id, raw) in (doc["exercises"] as? [String: Any]) ?? [:] {
            do { _ = try JSONDecoder().decode(ExercisePayload.self, from: Self.data(raw)) } catch {
                Issue.record("exercise \(id): \(error)")
            }
        }
        for (id, raw) in (doc["steps"] as? [String: Any]) ?? [:] {
            do { _ = try JSONDecoder().decode(StepPayload.self, from: Self.data(raw)) } catch {
                Issue.record("step \(id): \(error)")
            }
        }
        for (id, raw) in (doc["notes"] as? [String: Any]) ?? [:] {
            do { _ = try JSONDecoder().decode(NoteBody.self, from: Self.data(raw)) } catch {
                Issue.record("note \(id): \(error)")
            }
        }
    }
}
