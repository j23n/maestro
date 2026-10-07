import Foundation
import LearningCore
import Testing

@testable import Storage

/// M2.11: the learning engine's `ContentIndex`, built from the pack's tables and its step and assessment payloads.
@Suite struct PackContentIndexTests {
    let reader: PackReader
    let index: ContentIndex

    init() async throws {
        reader = try PackReader(url: try TestPack.build())
        index = try await reader.contentIndex()
    }

    @Test func metaUnitsLessonsAndCanDos() {
        #expect(index.packVersion == "0.1.0" && index.contentHash == "test-hash")
        #expect(index.units.map(\.id) == ["u01", "u02", "u99"])
        #expect(index.finalUnit?.id == "u99" && index.courseUnits.count == 2)
        #expect(index.lessons.map(\.id) == ["u02.l1", "u02.l2"])
        #expect(index.canDos(in: "u02").map(\.id) == [
            "cd:order-food-drink", "cd:ask-price-pay", "cd:choose-tu-lei", "cd:pass-on-prices",
        ])
    }

    @Test func stepsCarryWhatTheirPayloadsReference() async throws {
        #expect(index.steps.map(\.id).first == "u01.step-writing")
        #expect(index.steps(in: "u02").map(\.ord) == Array(1...14))
        for step in try await reader.steps() {
            let indexed = try #require(index.step(step.id))
            #expect(indexed.kind == step.kind && indexed.strand == step.strand && indexed.lessonId == step.lessonId)
            #expect(indexed.presentationOrder == step.exerciseOrder)  // the same seeded mix as the player's
            #expect(indexed.textIds == step.textIds)
        }
        let practice = try #require(index.step("u02.l1.step-practice"))
        #expect(practice.block == ["u02.l1.ex01", "u02.l1.ex04"] && practice.mix == ["u02.l1.ex15", "u02.l1.ex17"])
        let preview = try #require(index.step("u02.l1.step-preview"))
        #expect(preview.exerciseIds.count == 3 && preview.introduces.count == 4)
        #expect(preview.introduces == preview.introduces.sorted())
        #expect(index.step("u02.l1.step-story")?.exerciseIds == ["u02.l1.q1", "u02.l1.q2", "u02.l1.q3"])
        #expect(index.step("u02.l1.step-note")?.noteId == "u02.l1.note")
        #expect(index.step("u02.step-talk")?.exerciseIds == ["u02.task.talk"])
        #expect(index.step("u02.step-fluency")?.textIds == ["u02.l1.story"])
        #expect(index.step("u02.step-opener")?.exerciseIds.isEmpty == true)
    }

    @Test func checksPlacementAndFinalComeFromPayloads() throws {
        let check = try #require(index.check(forUnit: "u02"))
        #expect(check.id == "u02.check" && check.stepId == "u02.step-check")
        #expect(check.passOverall == 0.7 && check.sectionMin == 0.5)
        #expect(check.sections.map(\.id) == ["listening"])
        #expect(check.exerciseIds == ["u02.check.01", "u02.check.02"])
        #expect(index.step("u02.step-check")?.checkId == "u02.check")
        #expect(index.step("u02.step-check")?.exerciseIds == check.exerciseIds)

        let placement = try #require(index.placement)
        #expect(placement.advanceThreshold == 4 && placement.blocks.map(\.unitId) == ["u01"])
        let final = try #require(index.finalCheck)
        #expect(final.id == "final" && final.indicativePassPerSection == 7)
        #expect(final.sections.map(\.id) == ["listening"] && final.sections[0].max == 12)
    }

    @Test func exercisesWithTargetsTagsAndRequirements() throws {
        #expect(index.exercises.count == TestPack.allExercisePayloads.count)
        let cloze = try #require(index.exercise("u02.l1.ex01"))
        #expect(cloze.format == .cloze && cloze.role == .learn && cloze.stepId == "u02.l1.step-practice")
        #expect(cloze.targets == [
            ItemSkillPair("g:indefinite-article", .recall), ItemSkillPair("g:noun-gender", .recall),
        ])
        #expect(cloze.tags == ["cd:order-food-drink"] && cloze.canDoTags == ["cd:order-food-drink"])
        #expect(cloze.requires.count == 3 && cloze.requires == cloze.requires.sorted())
        #expect(index.exercise("u02.task.talk")?.targets.isEmpty == true)
        #expect(index.exercise("u02.check.01")?.role == .check)
        let recallers = index.exercises(targeting: ItemSkillPair("w:cornetto", .recall)).map(\.id)
        #expect(recallers.contains("u02.l1.ex04") && recallers.count == 3)
    }

    /// `exercise_targets` has no order; a match's targets follow its payload (`targets[i]` belongs to `pairs[i]`).
    @Test func matchTargetsKeepTheAuthoredOrder() async throws {
        let generated = try #require(index.exercise("u02.l1.step-preview.b1.match"))
        #expect(generated.targets == [ItemSkillPair("w:oggi", .read), ItemSkillPair("w:caffe", .read)])
        let payload = try await reader.exercise("u02.l1.step-preview.b1.match").payload
        #expect(generated.targets == payload.targets.map { ItemSkillPair($0.itemId, $0.skill) })
        let authored = [ItemSkillPair("w:caffe", .read), ItemSkillPair("w:oggi", .read)]
        #expect(index.exercise("u02.l1.ex20")?.targets == authored)
    }

    @Test func aMatchWhoseTargetsDisagreeWithTheTableIsMalformed() async throws {
        let reader = try PackReader(url: try TestPack.build { db in
            try db.execute(sql: "DELETE FROM exercise_targets WHERE exercise_id = 'u02.l1.ex20' AND item_id = 'w:oggi'")
        })
        await #expect(throws: PackError.malformedRow(table: "exercises", id: "u02.l1.ex20",
                                                     reason: "payload targets differ from exercise_targets")) {
            try await reader.contentIndex()
        }
    }

    @Test func itemsTextsNotesAndSounds() throws {
        #expect(index.items.count == 12)
        let cornetto = try #require(index.item("w:cornetto"))
        #expect(cornetto.displayForm == "il cornetto" && cornetto.gender == .m && cornetto.altGlosses == ["pastry"])
        #expect(cornetto.scheduledSkills == [.recall] && cornetto.status(.speak) == .P)
        #expect(index.item("w:caffe")?.primaryGloss == "coffee")
        #expect(index.items(in: "u01").map(\.id) == ["w:ciao"])
        #expect(index.scheduledPairs.contains(ItemSkillPair("s:double-consonants", .listen)))
        #expect(index.scheduledPairs.contains(ItemSkillPair("w:lei", .read)))
        #expect(!index.scheduledPairs.contains(ItemSkillPair("w:cornetto", .read)))

        #expect(index.texts.count == 5)
        #expect(index.text("u02.l1.story")?.requires == [
            ItemSkillPair("c:vorrei", .read), ItemSkillPair("w:cappuccino", .read),
        ])
        #expect(index.note("u02.l1.note")?.itemIds == ["g:indefinite-article", "g:noun-gender"])
        #expect(index.note("u02.l1.note")?.stepId == "u02.l1.step-note")
        #expect(index.sound("s:double-consonants")?.pairs.map { $0.map(\.it) } == [["eco", "ecco"], ["pena", "penna"]])
    }

    /// The engine runs on the index: a fresh learner continues at the first step, and entering the story needs the
    /// mini-preview for what the story requires but nobody introduced.
    @Test func theEngineRunsOnTheIndex() throws {
        let state = Replay.initialState(content: index)
        #expect(Progression.continuePoint(state: state, content: index)?.stepId == "u01.step-writing")
        let story = try #require(index.step("u02.l1.step-story"))
        let entry = Eligibility.enter(story, state: state, content: index)
        #expect(entry.missing.contains(ItemSkillPair("c:vorrei", .read)))
        #expect(entry.missing.contains(ItemSkillPair("w:cappuccino", .read)))
    }
}
