import Foundation

@testable import LearningCore

/// A synthetic course shaped like the golden Unit 2 Lesson 1 (docs/06): per unit an opener, one lesson (preview,
/// story, note, practice with block and mix, sounds in even units, use), a task conversation and talk, a check with
/// four sections, and fluency replay; placement blocks for Units 1–8 and a final check. `step_introduces` comes from
/// `IntroductionRules`, so the helper and the reducer are exercised together.
///
/// IDs per unit `uNN`: nouns `w:uNN-n1…n4` (P, alternating m/f, recall scheduled), adverb `w:uNN-a1` (P), story word
/// `w:uNN-s1` (R, read scheduled, introduced by the story), chunk `c:uNN-c1` (P, exemplifies `g:uNN-gr`), grammar
/// `g:uNN-gp` (P, recall scheduled) and `g:uNN-gr` (R, read scheduled), sound `s:uNN-s` (even units, listen).
enum TestCourse {
    static func u(_ k: Int) -> String { String(format: "u%02d", k) }
    static func noun(_ k: Int, _ j: Int) -> ItemID { ItemID("w:\(u(k))-n\(j)") }
    static func adverb(_ k: Int) -> ItemID { ItemID("w:\(u(k))-a1") }
    static func storyWord(_ k: Int) -> ItemID { ItemID("w:\(u(k))-s1") }
    static func chunk(_ k: Int) -> ItemID { ItemID("c:\(u(k))-c1") }
    static func grammarP(_ k: Int) -> ItemID { ItemID("g:\(u(k))-gp") }
    static func grammarR(_ k: Int) -> ItemID { ItemID("g:\(u(k))-gr") }
    static func sound(_ k: Int) -> ItemID { ItemID("s:\(u(k))-s") }
    static func step(_ k: Int, _ name: String) -> StepID { StepID("\(u(k)).l1.step-\(name)") }
    static func unitStep(_ k: Int, _ name: String) -> StepID { StepID("\(u(k)).step-\(name)") }
    static func ex(_ k: Int, _ n: Int) -> ExerciseID { ExerciseID(String(format: "\(u(k)).l1.ex%02d", n)) }
    static func checkEx(_ k: Int, _ n: Int) -> ExerciseID { ExerciseID(String(format: "\(u(k)).check.%02d", n)) }
    static func checkId(_ k: Int) -> CheckID { CheckID("\(u(k)).check") }
    static func unitId(_ k: Int) -> UnitID { UnitID(u(k)) }
    static func canDo(_ k: Int, _ x: String) -> CanDoID { CanDoID("cd:\(u(k))-\(x)") }

    static func p(_ id: ItemID, _ s: Skill) -> ItemSkillPair { ItemSkillPair(id, s) }

    static let allP: [Skill: ContentIndex.SkillInfo] = [
        .read: .init(status: .P, scheduled: false), .listen: .init(status: .P, scheduled: false),
        .recall: .init(status: .P, scheduled: true), .speak: .init(status: .P, scheduled: false),
    ]
    static let allR: [Skill: ContentIndex.SkillInfo] = [
        .read: .init(status: .R, scheduled: true), .listen: .init(status: .R, scheduled: false),
        .recall: .init(status: .R, scheduled: false), .speak: .init(status: .R, scheduled: false),
    ]

    static func make(units count: Int = 13, withFinal: Bool = true, packVersion: String = "0.1.0",
                     contentHash: String = "hash-1") -> ContentIndex
    {
        var units: [ContentIndex.Unit] = []
        var lessons: [ContentIndex.Lesson] = []
        var items: [ContentIndex.Item] = []
        var exercises: [ContentIndex.Exercise] = []
        var texts: [ContentIndex.Text] = []
        var notes: [ContentIndex.Note] = []
        var canDos: [ContentIndex.CanDo] = []
        var checks: [ContentIndex.Check] = []
        var sounds: [ContentIndex.Sound] = []
        var rawSteps: [IntroductionRules.RawStep] = []
        var rawItems: [ItemID: IntroductionRules.RawItem] = [:]
        // Steps without their introductions; filled from IntroductionRules at the end.
        var stepSpecs: [(id: StepID, unit: UnitID, lesson: LessonID?, ord: Int, kind: StepKind, strand: Strand,
                         exercises: [ExerciseID], block: [ExerciseID], mix: [ExerciseID], texts: [TextID],
                         note: NoteID?, check: CheckID?)] = []

        func addItem(_ item: ContentIndex.Item, grammarStatus: ItemStatus? = nil, exemplifies: [ItemID] = []) {
            items.append(item)
            rawItems[item.id] = IntroductionRules.RawItem(
                id: item.id, kind: item.kind, unitId: item.unitId, skills: item.skills.mapValues(\.status),
                grammarStatus: grammarStatus, exemplifies: exemplifies)
        }

        for k in 0..<count {
            let unit = unitId(k)
            let lesson = LessonID("\(u(k)).l1")
            units.append(.init(id: unit, ord: k))
            lessons.append(.init(id: lesson, unitId: unit, ord: 1))
            for j in 1...4 {
                let name = "nome\(k)x\(j)"
                let m = j % 2 == 1
                addItem(.init(id: noun(k, j), it: name, gloss: "thing \(k)-\(j); object", pos: "noun",
                              gender: m ? .m : .f, displayDef: (m ? "il " : "la ") + name,
                              displayIndef: (m ? "un " : "una ") + name, topics: ["topic:t\(j % 2)"], unitId: unit,
                              lessonId: lesson, skills: allP))
            }
            addItem(.init(id: adverb(k), it: "avv\(k)", gloss: "adverb \(k)", pos: "adv", unitId: unit,
                          lessonId: lesson, skills: allP))
            addItem(.init(id: storyWord(k), it: "parola\(k)", gloss: "word \(k)", pos: "noun", gender: .f,
                          displayDef: "la parola\(k)", displayIndef: "una parola\(k)", topics: ["topic:t0"],
                          unitId: unit, lessonId: lesson, skills: allR))
            addItem(.init(id: chunk(k), it: "frase \(k)…?", gloss: "phrase \(k)", unitId: unit, lessonId: lesson,
                          skills: allP), exemplifies: [grammarR(k)])
            addItem(.init(id: grammarP(k), it: "rule P \(k)", gloss: "rule P \(k)", unitId: unit, lessonId: lesson,
                          skills: [.read: .init(status: .P, scheduled: false),
                                   .recall: .init(status: .P, scheduled: true)]),
                    grammarStatus: .P)
            addItem(.init(id: grammarR(k), it: "rule R \(k)", gloss: "rule R \(k)", unitId: unit, lessonId: lesson,
                          skills: [.read: .init(status: .R, scheduled: true),
                                   .recall: .init(status: .R, scheduled: false)]),
                    grammarStatus: .R)
            let hasSound = k % 2 == 0
            if hasSound {
                addItem(.init(id: sound(k), it: "suono \(k)", gloss: "sound \(k)", unitId: unit, lessonId: lesson,
                              skills: [.listen: .init(status: .P, scheduled: true)]))
                sounds.append(.init(itemId: sound(k), pairs: [
                    [.init(it: "pena\(k)"), .init(it: "penna\(k)")], [.init(it: "caro\(k)"), .init(it: "carro\(k)")],
                ]))
            }
            canDos.append(.init(id: canDo(k, "a"), unitId: unit, ord: 1))
            canDos.append(.init(id: canDo(k, "b"), unitId: unit, ord: 2))

            // Exercises.
            func add(_ id: ExerciseID, _ format: ExerciseFormat, step: StepID?, role: ExerciseRole = .learn,
                     score: Int = 1, targets: [ItemSkillPair] = [], tags: [String] = [],
                     requires: [ItemSkillPair] = [])
            {
                exercises.append(.init(id: id, format: format, unitId: unit, stepId: step, role: role, score: score,
                                       targets: targets, tags: tags, requires: requires))
            }
            let previewItems = (1...4).map { noun(k, $0) } + [adverb(k), chunk(k)]
            let preview = step(k, "preview")
            let pMatch = ExerciseID("\(preview.rawValue).b1.match")
            add(pMatch, .match, step: preview, targets: previewItems.map { p($0, .read) },
                requires: previewItems.map { p($0, .read) })
            var previewExercises = [pMatch]
            for id in previewItems {
                let e = ExerciseID("\(preview.rawValue).b1.\(id.rawValue.replacingOccurrences(of: ":", with: "-"))")
                add(e, .recall, step: preview, targets: [p(id, .recall)], requires: [p(id, .recall)])
                previewExercises.append(e)
            }

            let story = step(k, "story")
            let storyText = TextID("\(u(k)).l1.story")
            var storyRequires = previewItems.map { p($0, .read) }
            if k > 0 { storyRequires += [p(noun(k - 1, 1), .read), p(grammarP(k - 1), .read)] }
            texts.append(.init(id: storyText, unitId: unit, requires: storyRequires))
            let q1 = ExerciseID("\(u(k)).l1.q1")
            add(q1, .choice, step: story, role: .comprehension, requires: [p(noun(k, 1), .read)])

            let note = step(k, "note")
            let noteId = NoteID("\(u(k)).l1.note")
            notes.append(.init(id: noteId, stepId: note, itemIds: [grammarP(k), grammarR(k)]))

            let practice = step(k, "practice")
            add(ex(k, 1), .cloze, step: practice, targets: [p(grammarP(k), .recall)], tags: [canDo(k, "a").rawValue],
                requires: [p(grammarP(k), .recall), p(noun(k, 1), .read)])
            for j in 1...4 {
                add(ex(k, 1 + j), .recall, step: practice, targets: [p(noun(k, j), .recall)],
                    requires: [p(noun(k, j), .recall)])
            }
            add(ex(k, 6), .sentenceBuilding, step: practice, targets: [p(adverb(k), .recall)],
                requires: [p(adverb(k), .recall), p(noun(k, 1), .recall)])
            add(ex(k, 7), .dictation, step: practice, targets: [p(noun(k, 1), .listen)],
                requires: [p(noun(k, 1), .listen)])
            add(ex(k, 8), .repeat, step: practice, targets: [p(chunk(k), .speak)], requires: [p(chunk(k), .speak)])
            add(ex(k, 10), .choice, step: practice, targets: [p(storyWord(k), .read)],
                requires: [p(storyWord(k), .read)])
            add(ex(k, 11), .choice, step: practice, targets: [p(grammarR(k), .read)],
                requires: [p(grammarR(k), .read), p(chunk(k), .read)])
            add(ex(k, 12), .cloze, step: practice, targets: [p(grammarP(k), .recall)],
                requires: [p(grammarP(k), .recall), p(noun(k, 2), .read)])
            add(ex(k, 13), .match, step: practice, targets: [p(noun(k, 1), .read), p(noun(k, 2), .read)],
                requires: [p(noun(k, 1), .read), p(noun(k, 2), .read)])
            var mix = [ex(k, 10), ex(k, 11), ex(k, 12), ex(k, 13)]
            if k > 0 {
                add(ex(k, 14), .recall, step: practice, targets: [p(noun(k - 1, 3), .recall)],
                    requires: [p(noun(k - 1, 3), .recall)])
                add(ex(k, 15), .cloze, step: practice, targets: [p(grammarP(k - 1), .recall)],
                    requires: [p(grammarP(k - 1), .recall), p(noun(k, 3), .read)])
                mix += [ex(k, 14), ex(k, 15)]
            }
            let block = (1...8).map { ex(k, $0) }

            let soundsStep = step(k, "sounds")
            if hasSound {
                add(ex(k, 20), .soundPair, step: soundsStep, targets: [p(sound(k), .listen)],
                    requires: [p(sound(k), .listen)])
                add(ex(k, 21), .soundPair, step: soundsStep, targets: [p(sound(k), .listen)],
                    requires: [p(sound(k), .listen)])
            }
            let use = step(k, "use")
            add(ex(k, 25), .conversation, step: use, tags: [canDo(k, "a").rawValue],
                requires: [p(chunk(k), .recall), p(noun(k, 1), .recall)])

            let conv = unitStep(k, "conversation-1")
            let convEx = ExerciseID("\(u(k)).task.conv1")
            add(convEx, .conversation, step: conv, tags: [canDo(k, "a").rawValue],
                requires: [p(chunk(k), .recall), p(noun(k, 2), .recall)])
            let talk = unitStep(k, "talk")
            let talkEx = ExerciseID("\(u(k)).task.talk")
            add(talkEx, .talk, step: talk, tags: [canDo(k, "b").rawValue], requires: [p(noun(k, 3), .recall)])

            // The check: listening, reading, writing, speaking.
            let checkStep = unitStep(k, "check")
            let a = canDo(k, "a").rawValue
            let b = canDo(k, "b").rawValue
            add(checkEx(k, 1), .choice, step: checkStep, role: .check, targets: [p(noun(k, 1), .listen)], tags: [a],
                requires: [p(noun(k, 1), .listen)])
            add(checkEx(k, 2), .dictation, step: checkStep, role: .check, targets: [p(noun(k, 2), .listen)],
                tags: ["sy:cefr.orthographic-control"], requires: [p(noun(k, 2), .listen)])
            add(checkEx(k, 3), .trueFalse, step: checkStep, role: .check, tags: [b],
                requires: [p(noun(k, 3), .read)])
            add(checkEx(k, 4), .choice, step: checkStep, role: .check, targets: [p(storyWord(k), .read)], tags: [b],
                requires: [p(storyWord(k), .read)])
            add(checkEx(k, 5), .cloze, step: checkStep, role: .check, targets: [p(grammarP(k), .recall)], tags: [a],
                requires: [p(grammarP(k), .recall)])
            add(checkEx(k, 6), .recall, step: checkStep, role: .check, targets: [p(noun(k, 3), .recall)], tags: [a],
                requires: [p(noun(k, 3), .recall)])
            add(checkEx(k, 7), .conversation, step: checkStep, role: .check, score: 2, tags: [a, b],
                requires: [p(chunk(k), .recall)])
            add(checkEx(k, 8), .talk, step: checkStep, role: .check, score: 2, tags: [b],
                requires: [p(noun(k, 4), .recall)])
            checks.append(.init(id: checkId(k), unitId: unit, stepId: checkStep, sections: [
                .init(id: "listening", exerciseIds: [checkEx(k, 1), checkEx(k, 2)]),
                .init(id: "reading", exerciseIds: [checkEx(k, 3), checkEx(k, 4)]),
                .init(id: "writing", exerciseIds: [checkEx(k, 5), checkEx(k, 6)]),
                .init(id: "speaking", exerciseIds: [checkEx(k, 7), checkEx(k, 8)]),
            ]))

            // Steps in unit order.
            var ord = 0
            func spec(_ id: StepID, _ kind: StepKind, _ strand: Strand, lesson: LessonID? = nil,
                      exercises: [ExerciseID] = [], block: [ExerciseID] = [], mix: [ExerciseID] = [],
                      texts: [TextID] = [], note: NoteID? = nil, check: CheckID? = nil)
            {
                stepSpecs.append((id, unit, lesson, ord, kind, strand, exercises, block, mix, texts, note, check))
                ord += 1
            }
            spec(unitStep(k, "opener"), .opener, .input)
            spec(preview, .preview, .languageFocus, lesson: lesson, exercises: previewExercises)
            rawSteps.append(.init(id: preview, unitId: unit, kind: .preview, previewItems: previewItems))
            spec(story, .story, .input, lesson: lesson, exercises: [q1], texts: [storyText])
            rawSteps.append(.init(id: story, unitId: unit, kind: .story, newTextItems: [storyWord(k)],
                                  detectedGrammar: [grammarR(k)]))
            spec(note, .note, .languageFocus, lesson: lesson, note: noteId)
            rawSteps.append(.init(id: note, unitId: unit, kind: .note, noteGrammar: [grammarP(k), grammarR(k)]))
            spec(practice, .practice, .languageFocus, lesson: lesson, block: block, mix: mix)
            if hasSound {
                spec(soundsStep, .sounds, .languageFocus, lesson: lesson, exercises: [ex(k, 20), ex(k, 21)])
                rawSteps.append(.init(id: soundsStep, unitId: unit, kind: .sounds, soundItems: [sound(k)]))
            }
            spec(use, .use, .output, lesson: lesson, exercises: [ex(k, 25)])
            spec(conv, .conversation, .output, exercises: [convEx])
            spec(talk, .talk, .output, exercises: [talkEx])
            spec(checkStep, .check, .assessment, check: checkId(k))
            spec(unitStep(k, "fluency"), .fluency, .fluency, texts: [storyText])
        }

        // Placement blocks for Units 1–8 and a final check.
        var blocks: [ContentIndex.PlacementAssessment.Block] = []
        for k in 1...8 where k < count {
            let ids = (1...5).map { ExerciseID("pl.\(u(k)).\($0)") }
            for (n, id) in ids.enumerated() {
                let format: ExerciseFormat = n < 2 ? .recall : n < 4 ? .cloze : .choice
                exercises.append(.init(id: id, format: format, unitId: unitId(k), role: .placement,
                                       targets: [p(noun(k, n % 4 + 1), .recall)]))
            }
            blocks.append(.init(unitId: unitId(k), exerciseIds: ids))
        }
        var finalCheck: ContentIndex.FinalAssessment?
        if withFinal {
            let finalUnit = UnitID("u99")
            units.append(.init(id: finalUnit, ord: 99, kind: .final))
            let review = StepID("u99.l1.step-practice")
            let reviewEx = ExerciseID("u99.l1.ex01")
            exercises.append(.init(id: reviewEx, format: .recall, unitId: finalUnit, stepId: review,
                                   targets: [p(noun(0, 1), .recall)], requires: [p(noun(0, 1), .recall)]))
            stepSpecs.append((review, finalUnit, LessonID("u99.l1"), 0, .practice, .languageFocus, [], [reviewEx], [],
                              [], nil, nil))
            var sections: [ContentIndex.CheckSection] = []
            for section in ["listening", "reading", "structures", "writing", "speaking"] {
                let ids = (1...3).map { ExerciseID("fin.\(section).0\($0)") }
                for id in ids {
                    exercises.append(.init(id: id, format: .choice, unitId: finalUnit, role: .final, score: 4,
                                           targets: [p(noun(0, 2), .read)]))
                }
                sections.append(.init(id: section, exerciseIds: ids, max: 12))
            }
            finalCheck = .init(sections: sections)
        }

        let introduces = IntroductionRules.stepIntroduces(steps: rawSteps, items: rawItems)
        let steps = stepSpecs.map { s in
            ContentIndex.Step(id: s.id, unitId: s.unit, lessonId: s.lesson, ord: s.ord, kind: s.kind, strand: s.strand,
                              exerciseIds: s.exercises, block: s.block, mix: s.mix, textIds: s.texts, noteId: s.note,
                              checkId: s.check, introduces: introduces[s.id] ?? [])
        }
        return ContentIndex(packVersion: packVersion, contentHash: contentHash, units: units, lessons: lessons,
                            steps: steps, items: items, exercises: exercises, texts: texts, notes: notes,
                            canDos: canDos, checks: checks,
                            placement: blocks.isEmpty ? nil : .init(advanceThreshold: 4, blocks: blocks),
                            finalCheck: finalCheck, sounds: sounds)
    }

    /// The course used by most tests (built once).
    static let standard = make()
    /// A small course for the many-run simulations.
    static let small = make(units: 3, withFinal: false)
}
