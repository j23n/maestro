import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Introductions and eligibility, § Unit progression.
@Suite struct EligibilityTests {
    typealias C = TestCourse
    let content = TestCourse.standard

    func p(_ id: ItemID, _ s: Skill) -> ItemSkillPair { ItemSkillPair(id, s) }

    @Test func stepsIntroducePerTheTable() throws {
        // Preview: read and listen, plus recall and speak where P.
        let preview = try #require(content.step(C.step(0, "preview")))
        #expect(Set(preview.introduces).isSuperset(of: [p(C.noun(0, 1), .read), p(C.noun(0, 1), .listen),
                                                        p(C.noun(0, 1), .recall), p(C.noun(0, 1), .speak)]))
        // ...and the R point exemplified by a chunk of the preview, read only.
        #expect(preview.introduces.contains(p(C.grammarR(0), .read)))
        // Story: items flagged new in the text, read and listen.
        #expect(try #require(content.step(C.step(0, "story"))).introduces
                == [p(C.storyWord(0), .read), p(C.storyWord(0), .listen)])
        // Note: the P point read and recall; the R point was already introduced by the earlier preview.
        #expect(try #require(content.step(C.step(0, "note"))).introduces
                == [p(C.grammarP(0), .read), p(C.grammarP(0), .recall)])
        // Sounds: listen.
        #expect(try #require(content.step(C.step(0, "sounds"))).introduces == [p(C.sound(0), .listen)])
        #expect(try #require(content.step(C.step(0, "practice"))).introduces.isEmpty)
    }

    @Test func grammarPointRule() {
        let u1: UnitID = "u01"
        let u2: UnitID = "u02"
        let items: [ItemID: IntroductionRules.RawItem] = [
            "g:p": .init(id: "g:p", unitId: u2, grammarStatus: .P),
            "g:r": .init(id: "g:r", unitId: u2, grammarStatus: .R),
            "g:chunk": .init(id: "g:chunk", unitId: u2, grammarStatus: .chunk),
            "g:late": .init(id: "g:late", unitId: u2, grammarStatus: .R),
            "c:scusi": .init(id: "c:scusi", unitId: u1, skills: [.read: .P], exemplifies: ["g:late"]),
            "c:vorrei": .init(id: "c:vorrei", unitId: u2, skills: [.read: .P], exemplifies: ["g:r"]),
        ]
        let steps: [IntroductionRules.RawStep] = [
            .init(id: "u01.l1.step-preview", unitId: u1, kind: .preview, previewItems: ["c:scusi"]),
            .init(id: "u02.l1.step-preview", unitId: u2, kind: .preview, previewItems: ["c:vorrei"]),
            .init(id: "u02.l1.step-story", unitId: u2, kind: .story, detectedGrammar: ["g:p", "g:r", "g:chunk"]),
            .init(id: "u02.l1.step-note", unitId: u2, kind: .note, noteGrammar: ["g:p", "g:r"]),
            .init(id: "u02.l2.step-listening", unitId: u2, kind: .listening, detectedGrammar: ["g:late"]),
        ]
        let result = IntroductionRules.stepIntroduces(steps: steps, items: items)
        // R point: the first preview in its own unit with an exemplifying chunk beats its note.
        #expect(result["u02.l1.step-preview"]?.contains(p("g:r", .read)) == true)
        #expect(result["u02.l1.step-note"] == [p("g:p", .read), p("g:p", .recall)])
        // A chunk point with no note and no exemplifying preview: the first story where it is detected.
        #expect(result["u02.l1.step-story"] == [p("g:chunk", .read)])
        // A chunk from an earlier unit never introduces a later point; detection in its own unit does.
        #expect(result["u01.l1.step-preview"]?.contains(p("g:late", .read)) == false)
        #expect(result["u02.l2.step-listening"] == [p("g:late", .read)])
        // P points only through their note: never by detection.
        #expect(!(result["u02.l1.step-story"] ?? []).contains(p("g:p", .read)))
    }

    @Test func enteringAStepIntroducesItsItemsThenChecksEligibility() throws {
        let d = TestDevice()
        let preview = try #require(content.step(C.step(0, "preview")))
        let entry = Eligibility.enter(preview, state: d.state, content: content)
        #expect(entry.via == .preview)
        #expect(entry.introductions == preview.introduces.sorted())
        #expect(!entry.needsMiniPreview)  // everything it shows, it introduces itself
        d.enter(preview.id)
        let intro = try #require(d.events.compactMap { e -> IntroducedPayload? in
            if case .introduced(let p) = e.payload { return p }
            return nil
        }.first)
        #expect(intro.via == .preview)
        #expect(intro.stepId == preview.id)
        #expect(Set(intro.pairs) == Set(preview.introduces))
        // Entering again introduces nothing new.
        #expect(Eligibility.enter(preview, state: d.state, content: content).introductions.isEmpty)
        for id in preview.exerciseIds {
            #expect(Eligibility.isEligible(exercise: try #require(content.exercise(id)), state: d.state))
        }
    }

    @Test func aMissingIntroductionGivesTheMiniPreviewSignal() throws {
        // Unit 1's story needs Unit 0 items; a learner who jumped straight to it hasn't met them.
        let d = TestDevice()
        let story = try #require(content.step(C.step(1, "story")))
        #expect(!Eligibility.isEligible(text: "u01.l1.story", state: d.state, content: content))
        let entry = Eligibility.enter(story, state: d.state, content: content)
        #expect(entry.needsMiniPreview)
        #expect(entry.missing.contains(p(C.noun(0, 1), .read)))
        #expect(entry.missing.contains(p(C.grammarP(0), .read)))
        #expect(!entry.missing.contains(p(C.storyWord(1), .read)))  // the step introduces it itself
        #expect(entry.miniPreviewItems.contains(C.noun(0, 1)))
        let catchup = try #require(entry.catchupPayload)
        #expect(catchup.via == .catchup)
        #expect(Set(catchup.pairs) == Set(entry.missing))
        d.enter(story.id)  // writes stepStarted, the story's introductions and the catchup
        #expect(d.state.introductions[p(C.noun(0, 1), .read)]?.via == .catchup)
        #expect(d.state.introductions[p(C.storyWord(1), .read)]?.via == .story)
        #expect(!Eligibility.enter(story, state: d.state, content: content).needsMiniPreview)
        #expect(Eligibility.isEligible(text: "u01.l1.story", state: d.state, content: content))
        // Only the missing pairs are introduced: recall of the Unit 0 noun is still unknown.
        #expect(!d.state.isIntroduced(p(C.noun(0, 1), .recall)))
    }

    @Test func placementIntroducedItemsMakeTheStartUnitEligible() throws {
        let d = TestDevice()
        let introduced = try #require(Introductions.placementPayload(startUnit: "u03", content: content))
        d.record(d.factory.placementCompleted(PlacementCompletedPayload(startUnit: "u03", blocks: [])))
        d.record(d.factory.introduced(introduced))
        for k in 0..<3 {
            #expect(d.state.introductions[p(C.noun(k, 2), .recall)]?.via == .placement)
            #expect(d.state.introductions[p(C.storyWord(k), .read)]?.via == .placement)
            #expect(!d.state.isIntroduced(p(C.storyWord(k), .recall)))  // R: read and listen only
            #expect(d.state.isIntroduced(p(C.grammarP(k), .recall)))
            #expect(!d.state.isIntroduced(p(C.grammarR(k), .recall)))
        }
        #expect(d.state.isIntroduced(p(C.sound(2), .listen)))
        #expect(!d.state.isIntroduced(p(C.noun(3, 1), .read)))
        // Working through the start unit in order never needs a mini-preview.
        for step in content.steps(in: "u03") {
            let entry = try #require(d.enter(step.id))
            #expect(!entry.needsMiniPreview, "\(step.id) needs a mini-preview")
            for id in step.presentationOrder { d.answer(id, .correct, step: step.id) }
            d.complete(step.id)
        }
    }

    @Test func stepsThatNeverIntroduceCannotCoverTheirOwnRequirements() throws {
        // A malformed pack lists step_introduces on a practice step: it must not hide what the step needs.
        let pair = p(C.noun(0, 1), .recall)
        let step = ContentIndex.Step(id: "u00.l1.step-practice", unitId: "u00", ord: 4, kind: .practice,
                                     block: [C.ex(0, 2)], introduces: [pair])
        let entry = Eligibility.enter(step, state: LearnerState(), content: content)
        #expect(entry.introductions.isEmpty)
        #expect(entry.missing == [pair])
    }

    @Test func eligibilityOfExercisesAndUnknownTexts() throws {
        let d = TestDevice()
        let exercise = try #require(content.exercise(C.ex(0, 1)))
        #expect(!Eligibility.isEligible(exercise: exercise, state: d.state))
        #expect(Eligibility.missing(exercise.requires, state: d.state)
                == [p(C.grammarP(0), .recall), p(C.noun(0, 1), .read)])
        d.record(d.factory.introduced(exercise.requires, via: .debug))
        #expect(Eligibility.isEligible(exercise: exercise, state: d.state))
        #expect(!Eligibility.isEligible(text: "nope", state: d.state, content: content))
    }

    // MARK: Progression

    @Test func continueIsTheFirstIncompleteStepOfTheEarliestAvailableUnit() throws {
        let d = TestDevice()
        #expect(Progression.continuePoint(state: d.state, content: content)?.stepId == C.unitStep(0, "opener"))
        d.run(C.unitStep(0, "opener"))
        d.run(C.step(0, "preview"))
        #expect(Progression.continuePoint(state: d.state, content: content)?.stepId == C.step(0, "story"))
        d.completeCheck(0, passed: true)
        // Unit 0 is complete although some steps were never done; Unit 1 is next.
        #expect(Progression.continuePoint(state: d.state, content: content)?.stepId == C.unitStep(1, "opener"))
    }

    @Test func fluencyReplayNeverBlocks() {
        let d = TestDevice()
        for step in content.steps(in: "u00") where step.kind != .fluency && step.kind != .check { d.run(step.id) }
        #expect(Progression.continuePoint(state: d.state, content: content)?.stepId == C.unitStep(0, "check"))
        #expect(Progression.firstIncompleteStep(in: "u00", state: d.state, content: content)?.kind == .check)
    }

    @Test func placementSkipsUnitsAndStartFromTheBeginningSkipsNone() {
        let d = TestDevice()
        d.enter(C.unitStep(0, "opener"))  // started before placing
        d.record(d.factory.placementCompleted(PlacementCompletedPayload(startUnit: "u03", blocks: [])))
        #expect((0..<3).map { d.state.unitState(C.unitId($0)) } == [.skipped, .skipped, .skipped])
        #expect(d.state.unitState("u03") == .available)
        #expect(d.state.unitState("u04") == .locked)
        #expect(Progression.continuePoint(state: d.state, content: content)?.unitId == "u03")
        d.completeCheck(3, passed: false)
        #expect(d.state.unitState("u04") == .available)

        let fresh = TestDevice()
        fresh.record(fresh.factory.placementCompleted(PlacementCompletedPayload(startUnit: "u00", blocks: [])))
        #expect(fresh.state.unitState("u00") == .available)
        #expect(fresh.state.unitState("u01") == .locked)
        #expect(fresh.state.introductions.isEmpty)
    }

    @Test func aCompletedUnitStaysCompletedAfterALaterPlacement() {
        let d = TestDevice()
        d.completeCheck(0, passed: true)
        d.record(d.factory.placementCompleted(PlacementCompletedPayload(startUnit: "u02", blocks: [])))
        #expect(d.state.unitState("u00") == .completed)
        #expect(d.state.unitState("u01") == .skipped)
        #expect(d.state.unitState("u02") == .available)
    }
}
