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

    @Test func advancingReportsStepChanges() throws {
        let m = LessonPlayerModel(bundle: try bundle())
        #expect(m.openingStep == "s0")
        #expect(m.advance() == .init(completed: "s0", started: "s1"))
        #expect(m.advance() == .init())  // meet cards → the batch's first exercise, same step
        while m.currentStep?.id != "s6" { m.advance() }
        #expect(m.advance() == .init(completed: "s6", started: nil))
        #expect(m.isFinished && m.advance() == .init())
    }

    @Test func resumeOpensAnUnstartedStepAtItsFirstPage() throws {
        let preview: Set<ExerciseID> = [
            "u02.l1.step-preview.b1.match", "u02.l1.step-preview.b1.w-caffe",
            "u02.l1.step-preview.b1.c-vorrei",
        ]
        let fresh = LessonPlayerModel(bundle: try bundle(), answered: preview)
        #expect(fresh.current?.page == .story("u02.l1.story"))  // read the story before its questions
        #expect(fresh.exerciseNumber == 3)
        let midStep = LessonPlayerModel(bundle: try bundle(), answered: preview.union(["u02.l1.q1"]))
        #expect(midStep.current?.page == .exercise("u02.l1.q2"))
        #expect(midStep.exerciseNumber == 5)
    }

    @Test func aPickedFinishedStepOpensAsARevisit() throws {
        let b = try bundle()
        let all = Set(
            LessonPlayerModel.flatten(b).compactMap { e -> ExerciseID? in
                if case .exercise(let id) = e.page { id } else { nil }
            })
        let revisit = LessonPlayerModel(bundle: b, answered: all, startingAt: "s2")
        #expect(revisit.current?.page == .story("u02.l1.story") && !revisit.isFinished)
        let ahead = LessonPlayerModel(bundle: b, answered: [], startingAt: "s4")
        #expect(ahead.position == 0)  // can't skip ahead of the resume point
    }

    @Test func everythingAnsweredMeansFinished() throws {
        let b = try bundle()
        let all = Set(
            LessonPlayerModel.flatten(b).compactMap { e -> ExerciseID? in
                if case .exercise(let id) = e.page { id } else { nil }
            })
        let m = LessonPlayerModel(bundle: b, answered: all)
        #expect(m.isFinished && m.current == nil && m.progress == 1 && m.exerciseNumber == 14)
        m.advance()
        #expect(m.isFinished)
    }

    @Test func listeningEndsWithItsTranscript() throws {
        let listening = try #require(try PayloadFixtures.steps().first { $0.kind == .listening })
        let b = LessonBundle(
            lessonID: "u02.l2", unitID: "u02", title: "L2",
            steps: [.init(id: "u02.l2.step-listening", title: "Listening", payload: listening)],
            exercises: [:])
        #expect(
            LessonPlayerModel.flatten(b).map(\.page)
                == [.listening("u02.l2.phone", plays: nil), .exercise("u02.l2.ex20"), .transcript("u02.l2.phone")])
    }

    @Test func checksGetASectionPageBeforeTheirExercises() throws {
        let check = try #require(try PayloadFixtures.steps().first { $0.kind == .check })
        let b = LessonBundle(
            lessonID: "u02.check", unitID: "u02", title: "Check",
            steps: [.init(id: "u02.check", title: "Unit 2 · Check", payload: check)], exercises: [:])
        let pages = LessonPlayerModel.flatten(b).map(\.page)
        #expect(
            pages == [
                .checkSection(id: "listening", title: "Listening"), .exercise("u02.check.01"),
                .exercise("u02.check.02"),
            ])
    }

    @Test func glossesComeFromTheTokenThenTheItem() throws {
        func token(
            _ s: String, _ kind: TokenKind, item: ItemID? = nil, gloss: String? = nil, flags: Int = 0
        )
            -> PackToken
        {
            PackToken(surface: s, trailing: " ", kind: kind, itemId: item, gloss: gloss, flags: flags)
        }
        let line = TokenizedText(
            text: "Vorrei un caffè, Marco", lead: "",
            tokens: [
                token("Vorrei", .word, item: "c:vorrei", flags: 1), token("un", .word, item: "g:indefinite-article"),
                token("caffè", .word, item: "w:caffe", gloss: "an espresso", flags: 1), token(",", .punct),
                token("Marco", .name),
            ])
        var b = try bundle()
        b.texts["u02.l1.story"] = PlayerText(
            id: "u02.l1.story", title: nil,
            lines: [PlayerLine(number: 1, speaker: "ch:marco", text: line, english: "I'd like a coffee")],
            audioID: nil, layout: nil)
        b.items = [
            "w:caffe": WordInfo(itemID: "w:caffe", display: "il caffè", partOfSpeech: "noun", gloss: "coffee"),
            "c:vorrei": WordInfo(
                itemID: "c:vorrei", display: "vorrei", partOfSpeech: "chunk", gloss: "I'd like",
                note: "Polite: use it to order."),
        ]
        let caffe = b.gloss(text: "u02.l1.story", line: 1, token: 2)
        #expect(caffe?.headword == "il caffè" && caffe?.posAndGloss == "noun · an espresso")
        #expect(b.gloss(text: "u02.l1.story", line: 1, token: 0)?.note == "Polite: use it to order.")
        #expect(b.gloss(text: "u02.l1.story", line: 1, token: 4) == nil)  // names aren't glossed
        #expect(b.gloss(text: "u02.l1.story", line: 2, token: 0) == nil)
        #expect(b.newWords(in: "u02.l1.story").map(\.itemID) == ["c:vorrei", "w:caffe"])
    }

    @Test func layoutStringsAreNumberedInReadingOrder() throws {
        let data = try Data(
            contentsOf: PayloadFixtures.repoRoot.appendingPathComponent(
                "fixtures/packs/payload-examples.json"))
        let doc = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        let raw = try #require((doc["layouts"] as? [[String: Any]])?.first)
        let layout = try JSONDecoder().decode(LayoutPayload.self, from: JSONSerialization.data(withJSONObject: raw))
        let strings = layout.strings
        #expect(!strings.isEmpty)
        #expect(layout.stringNumbers[strings[0]] == 1)
        #expect(Set(layout.stringNumbers.values).count == layout.stringNumbers.count)
    }

    /// CL33: a real-world text's English title is its caption wherever it is shown (a reading step, a task's or a
    /// check's source); other texts and untitled layouts have none.
    @Test func aRealWorldTextsEnglishTitleIsItsCaption() throws {
        let data = try Data(
            contentsOf: PayloadFixtures.repoRoot.appendingPathComponent("fixtures/packs/payload-examples.json"))
        let doc = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        let raw = try #require((doc["layouts"] as? [[String: Any]])?.first)
        let layout = try JSONDecoder().decode(LayoutPayload.self, from: JSONSerialization.data(withJSONObject: raw))
        func text(_ layout: LayoutPayload?, _ titleEn: String?) -> PlayerText {
            PlayerText(id: "u02.task.menu", title: nil, lines: [], audioID: nil, layout: layout, titleEn: titleEn)
        }
        let menu = text(layout, "Bar Aurora: the menu")
        #expect(menu.caption == "Bar Aurora: the menu")
        #expect(text(layout, nil).caption == nil && text(layout, "  ").caption == nil)
        #expect(text(nil, "Bar Aurora").caption == nil)  // a story's title is not a caption
        // The task's relay and the check's question show the same text, caption included.
        var b = try bundle()
        b.texts["u02.task.menu"] = menu
        #expect(b.source(for: try PayloadFixtures.exercise("u02.task.relay"))?.text.caption == "Bar Aurora: the menu")
        #expect(b.source(for: try PayloadFixtures.exercise("u02.check.03"))?.text.caption == "Bar Aurora: the menu")
    }

    @Test func exerciseSourcesResolveToTheirTextOrLine() throws {
        var b = try bundle()
        let menu = PlayerText(id: "u02.task.menu", title: nil, lines: [], audioID: nil, layout: nil)
        b.texts["u02.task.menu"] = menu
        let relay = try PayloadFixtures.exercise("u02.task.relay")
        #expect(b.source(for: relay) == SourceText(text: menu))
        let check = try PayloadFixtures.exercise("u02.check.03")
        #expect(b.source(for: check)?.text.id == "u02.task.menu")
        #expect(b.source(for: try PayloadFixtures.exercise("u02.l1.ex20")) == nil)
    }

    @Test func everyExampleExerciseGetsAViewModel() throws {
        for (id, payload) in try PayloadFixtures.exercises() {
            let host = ExerciseHostModel.make(payload, env: .preview(), sink: nil)
            #expect(host != nil, "\(id)")
            #expect(host?.isDone == false, "\(id)")
        }
    }
}
