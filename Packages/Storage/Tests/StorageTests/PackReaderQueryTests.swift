import Foundation
import GRDB
import LearningCore
import Testing

@testable import Storage

/// M2.11: every query against the test pack (TestPack), and every payload example decodes through the reader.
@Suite struct PackReaderQueryTests {
    let reader: PackReader

    init() throws { reader = try PackReader(url: try TestPack.build()) }

    static func decode<T: Decodable>(_ type: T.Type, _ object: Any) throws -> T {
        try JSONDecoder().decode(type, from: JSONSerialization.data(withJSONObject: object))
    }

    // MARK: Payloads

    /// The acceptance check: every example exercise comes back from the pack exactly as LearningCore decodes it.
    @Test func everyExampleExerciseDecodesThroughThePack() async throws {
        let examples = TestPack.exampleExercises
        let ids = TestPack.exampleExerciseIDs.map(ExerciseID.init(rawValue:))
        let fromPack = try await reader.exercises(ids)
        #expect(fromPack.count == examples.count)
        #expect(Set(fromPack.map(\.format)) == Set(ExerciseFormat.allCases))
        for (exercise, raw) in zip(fromPack, examples) {
            #expect(exercise.payload == (try Self.decode(ExercisePayload.self, raw)))
            #expect(exercise.estSeconds == 30)
        }
        let cloze = try await reader.exercise("u02.l1.ex01")
        #expect(cloze.sourceRef == "u02.l1.story#3")
        #expect(cloze.role == .learn && cloze.format == .cloze)
    }

    @Test func everyExampleStepDecodesThroughThePack() async throws {
        let steps = try await reader.steps(inUnit: "u02")
        #expect(steps.count == TestPack.exampleSteps.count)
        for raw in TestPack.exampleSteps {
            let payload = try Self.decode(StepPayload.self, raw)
            let step = try #require(steps.first { $0.kind == payload.kind })
            #expect(step.payload == payload)
        }
    }

    @Test func theNoteAssessmentsAndLayoutDecodeThroughThePack() async throws {
        let note = try await reader.note("u02.l1.note")
        #expect(note.body == (try Self.decode(NoteBody.self, TestPack.exampleNote)))
        #expect(note.grammar == ["g:indefinite-article", "g:noun-gender"])
        #expect(note.stepId == "u02.l1.step-note" && note.titleEn == "un, una and un'")
        #expect(try await reader.noteIDs(introducing: "g:noun-gender") == ["u02.l1.note"])
        #expect(try await reader.noteIDs(introducing: "w:caffe").isEmpty)

        let placement = try await reader.assessment(.placement)
        #expect(placement == (try Self.decode(AssessmentPayload.self, TestPack.exampleAssessments[0])))
        guard case .final(let pass, _)? = try await reader.assessment(.final) else {
            Issue.record("final")
            return
        }
        #expect(pass == 7)

        let menu = try await reader.text("u02.l2.menu")
        #expect(menu.kind == .realWorld && menu.lines.isEmpty)
        #expect(menu.layout == (try Self.decode(LayoutPayload.self, TestPack.exampleLayout)))
    }

    @Test func aPartialPackMayHaveNoAssessments() async throws {
        let reader = try PackReader(url: try TestPack.build { db in try db.execute(sql: "DELETE FROM assessments") })
        #expect(try await reader.assessment(.placement) == nil)
        #expect(try await reader.assessment(.final) == nil)
    }

    // MARK: Course

    @Test func unitsCanDosAndLessons() async throws {
        let units = try await reader.units()
        #expect(units.map(\.id) == ["u01", "u02", "u99"])
        #expect(units.map(\.kind) == [.unit, .unit, .final])
        let u02 = try await reader.unit("u02")
        #expect(u02.titleIt == "Al bar" && u02.estMinutes == 120)
        await #expect(throws: PackError.notFound(table: "units", id: "u42")) { try await reader.unit("u42") }

        #expect(try await reader.canDos().map(\.unitId) == ["u01", "u02", "u02", "u02", "u02"])
        let canDos = try await reader.canDos(inUnit: "u02")
        #expect(canDos.map(\.ord) == [1, 2, 3, 4])
        #expect(canDos.map(\.isStretch) == [false, false, true, false])
        #expect(canDos[0].cefrScale == "spoken-interaction" && canDos[1].cefrScale == nil)

        #expect(try await reader.lessons(inUnit: "u02").map(\.id) == ["u02.l1", "u02.l2"])
        #expect(try await reader.lesson("u02.l2").titleEn == "On the phone")
        await #expect(throws: PackError.notFound(table: "lessons", id: "u02.l9")) { try await reader.lesson("u02.l9") }
    }

    @Test func stepsInCourseUnitAndLessonOrder() async throws {
        let all = try await reader.steps()
        #expect(all.first?.id == "u01.step-writing")
        #expect(all.dropFirst().map(\.ord) == Array(1...14))
        let unit = try await reader.steps(inUnit: "u02")
        #expect(unit.first?.kind == .opener && unit.first?.lessonId == nil && unit.first?.titleEn == nil)
        #expect(unit.last?.kind == .fluency && unit.last?.strand == .fluency)
        let lesson = try await reader.steps(inLesson: "u02.l1")
        #expect(lesson.map(\.kind) == [.preview, .story, .note, .practice, .sounds, .use])

        let reading = try await reader.step("u02.l2.step-reading")
        #expect(reading.isDraft && reading.textIds == ["u02.l2.menu"])
        #expect(try await reader.step("u02.l1.step-story").isDraft == false)
        let fluency = try await reader.step("u02.step-fluency")
        #expect(fluency.textIds == ["u02.l1.story"] && fluency.estSeconds == 840)
        await #expect(throws: PackError.notFound(table: "steps", id: "x")) { try await reader.step("x") }
    }

    @Test func outlines() async throws {
        let outline = try await reader.unitOutline("u02")
        #expect(outline.unit.id == "u02" && outline.canDos.count == 4 && outline.lessons.count == 2)
        #expect(outline.steps.count == 14)
        #expect(outline.steps(inLesson: "u02.l2").map(\.kind) == [.listening, .reading])
        let course = try await reader.courseOutline()
        #expect(course.map(\.id) == ["u01", "u02", "u99"])
        #expect(course[1] == outline)
        #expect(course[2].steps.isEmpty && course[0].steps.map(\.kind) == [.writing])
    }

    @Test func aStepsExercisesComeInPresentationOrder() async throws {
        let practice = try await reader.step("u02.l1.step-practice")
        let exercises = try await reader.exercises(forStep: "u02.l1.step-practice")
        #expect(exercises.map(\.id) == practice.payload.exerciseOrder(stepID: practice.id))
        #expect(exercises.map(\.id) == practice.exerciseOrder)
        #expect(Array(exercises.prefix(2).map(\.id)) == ["u02.l1.ex01", "u02.l1.ex04"])
        let preview = try await reader.exercises(forStep: "u02.l1.step-preview")
        #expect(preview.map(\.format) == [.match, .recall, .recall])
        let check = try await reader.exercises(forStep: "u02.step-check")
        #expect(check.map(\.id) == ["u02.check.01", "u02.check.02"])
        #expect(try await reader.exercises(forStep: "u02.step-opener").isEmpty)
    }

    @Test func exercisesTargetingAPair() async throws {
        let ids = try await reader.exerciseIDs(targeting: ItemSkillPair("w:cornetto", .recall))
        #expect(ids == ["u02.l1.ex04", "u02.l1.step-preview.b1.c-vorrei", "u02.l1.step-preview.b1.w-caffe"])
        #expect(try await reader.exerciseIDs(targeting: ItemSkillPair("w:ciao", .recall)).isEmpty)
        await #expect(throws: PackError.notFound(table: "exercises", id: "gen:recall:w:caffe")) {
            try await reader.exercises(["u02.l1.ex01", "gen:recall:w:caffe"])
        }
    }

    // MARK: Items

    @Test func itemsWithSkillsAndRequirements() async throws {
        let cornetto = try await reader.item("w:cornetto")
        #expect(cornetto.kind == .word && cornetto.it == "cornetto" && cornetto.display == "il cornetto")
        #expect(cornetto.displayIndef == "un cornetto" && cornetto.gender == .m && cornetto.plural == "cornetti")
        #expect(cornetto.altGlossesEn == ["pastry"] && cornetto.topics == ["topic:food-drink"])
        #expect(cornetto.noteEn?.contains("brioche") == true && cornetto.audioId == "a:000000000002")
        #expect(cornetto.skills.count == 4 && cornetto.scheduledSkills == [.recall])
        #expect(cornetto.skills[.read] == ContentIndex.SkillInfo(status: .P, scheduled: false))
        #expect(cornetto.isCognate == false && cornetto.lessonId == "u02.l1")

        let caffe = try await reader.item("w:caffe")
        #expect(caffe.shortGloss == "coffee" && caffe.glossEn == "coffee; espresso")
        #expect(try await reader.item("w:cappuccino").isCognate)
        let article = try await reader.item("g:indefinite-article")
        #expect(article.requires == ["g:noun-gender"] && article.display == "un, uno, una, un'")
        #expect(try await reader.item("w:lei").scheduledSkills == [.read])
        await #expect(throws: PackError.notFound(table: "items", id: "w:nope")) { try await reader.item("w:nope") }

        let some = try await reader.items(["w:oggi", "c:vorrei", "w:caffe"])
        #expect(some.map(\.id) == ["w:oggi", "c:vorrei", "w:caffe"])
        #expect(try await reader.items(inUnit: "u01").map(\.id) == ["w:ciao"])
        let all = try await reader.allItems()
        #expect(all.count == 12 && all.map(\.id) == all.map(\.id).sorted())
        #expect(all.first { $0.id == "w:cornetto" } == cornetto)
        #expect(all.first { $0.id == "g:indefinite-article" } == article)
    }

    @Test func formsAndKnownForms() async throws {
        let forms = try await reader.forms(of: "w:cornetto")
        #expect(forms.map(\.form) == ["cornetti", "cornetto"] && forms[0].morph == "NOUN-M:p")
        let known = try await reader.knownForms()
        #expect(known.count == 6)
        #expect(known.areFormsOfSameItem("cornetto", "cornetti"))
        #expect(known.items(of: "caffè") == ["w:caffe"])
        #expect(TypedAnswerGrader(knownForms: known).knownForms == known)
    }

    /// Letter items (`items.letter`, schema 2): the spoken-spelling table for the transcript matchers (docs/05
    /// § Speech transcripts). The test pack's letters are added here so the other tests' item counts stay as they are.
    static func addLetters(_ db: Database, _ letters: [(id: String, kind: String, it: String, letter: String)]) throws {
        try TestPack.insert(db, "items", letters.map { l in
            ["id": l.id, "kind": l.kind, "it": l.it, "gloss_en": "the letter \(l.letter)", "unit_id": "u01",
             "lesson_id": "u01.l1", "letter": l.letter]
        })
    }

    @Test func letterNamesComeFromTheLetterItems() async throws {
        #expect(try await reader.letterNames().isEmpty)  // a pack without letter items: transcripts stay as they are
        let lettered = try PackReader(url: try TestPack.build { db in
            try Self.addLetters(db, [
                ("w:bi", "word", "bi", "B"), ("w:a~letter", "word", "a", "A"), ("c:i-lunga", "chunk", "i lunga", "J"),
            ])
        })
        let names = try await lettered.letterNames()
        #expect(names.count == 3)
        #expect(names.name(of: "J") == ["i", "lunga"] && names.name(of: "b") == ["bi"])
        #expect(names.name(of: "a") == ["a"])
        #expect(names.apply(["b", "a", "j"]) == ["bi", "a", "i", "lunga"])
        let report = try await lettered.verify()
        #expect(report.problems == [] && report.decoded["letters"] == 3)
        let marco = try AnswerPattern("bi, a, i lunga")
        #expect(TranscriptMatcher(letterNames: names).match(transcript: "B-A-J", accepted: marco)?.passed == true)
    }

    @Test func theSchemaKeepsOneItemPerLetterAndOnlyCapitalLetters() throws {
        for letters in [[("w:bi", "word", "bi", "B"), ("w:be", "word", "be", "B")], [("w:bi", "word", "bi", "b")],
                        [("w:bi", "word", "bi", "BI")]] {
            #expect(throws: DatabaseError.self) {
                _ = try TestPack.build { db in try Self.addLetters(db, letters) }
            }
        }
    }

    @Test func aLetterWithoutANameIsMalformed() async throws {
        let reader = try PackReader(url: try TestPack.build { db in
            try Self.addLetters(db, [("w:bi", "word", "bi", "B"), ("w:dots", "word", "…", "Q")])
        })
        let unnamed = PackError.malformedRow(table: "items", id: "w:dots", reason: "the letter Q has no name ('…')")
        await #expect(throws: unnamed) { try await reader.letterNames() }
        let report = try await reader.verify()
        #expect(report.problems.contains(unnamed))
        #expect(report.decoded["letters"] == nil)
    }

    @Test func soundPairsAcceptObjectsAndBareWords() async throws {
        let pairs = try await reader.soundPairs(of: "s:double-consonants")
        #expect(pairs.count == 2)
        let ecco = ContentIndex.SoundWord(it: "ecco", audioId: "a:000000000002")
        #expect(pairs[0] == [ContentIndex.SoundWord(it: "eco"), ecco])
        #expect(pairs[1].map(\.it) == ["pena", "penna"] && pairs[1].allSatisfy { $0.audioId == nil })
        #expect(try await reader.soundPairs(of: "w:caffe").isEmpty)
    }

    @Test func searchFindsItalianFormsAndEnglishGlosses() async throws {
        let index = try await reader.searchIndex()
        #expect(index.count == 12)
        #expect(index.search("caffe").first?.id == "w:caffe")  // accents ignored
        #expect(index.search("CAFFÈ").first?.id == "w:caffe")
        #expect(index.search("cornetti").map(\.id) == ["w:cornetto"])  // a surface form
        #expect(index.search("croissant").map(\.id) == ["w:cornetto"])  // English
        #expect(index.search("past").map(\.id) == ["w:cornetto"])  // an alternative gloss, word start
        #expect(index.search("il cap").first?.id == "w:cappuccino")  // the display form
        // Italian word starts (ties by unit, then ID) rank above an English word start (*coffee*).
        #expect(index.search("co").map(\.id) == ["s:double-consonants", "w:cornetto", "w:caffe"])
        #expect(index.search("co", limit: 1).map(\.id) == ["s:double-consonants"])
        #expect(index.search("co") { $0.kind == .word }.map(\.id) == ["w:cornetto", "w:caffe"])
        #expect(index.search("co") { $0.unitId == "u01" }.isEmpty)
        #expect(index.search("  ").isEmpty && index.search("zzz").isEmpty)
    }

    // MARK: Texts and audio

    @Test func aStoryWithLinesTokensAndTimings() async throws {
        let story = try await reader.text("u02.l1.story")
        #expect(story.kind == .story && story.titleIt == "Bar Aurora" && story.layout == nil)
        #expect(story.audioId == "a:000000000001" && story.durationMs == 5_000)
        #expect(story.lines.map(\.number) == [1, 2, 3])
        let first = story.lines[0]
        #expect(first.speakerId == "ch:narrator" && first.addresseeId == nil && first.register == nil)
        #expect(first.text.rebuilt == first.text.text && first.text.lead.isEmpty)
        #expect(first.tokenTimings.count == first.text.tokens.count)
        #expect(first.tokenTimings.last == .some(nil))  // punctuation has no timing
        let second = story.lines[1]
        #expect(second.register == .lei && second.addresseeId == "ch:marco")
        #expect(second.text.tokens[3].gloss == "will you have")  // context gloss
        let third = story.lines[2]
        #expect(third.text.lead == "«" && third.text.rebuilt == third.text.text)
        #expect(third.text.tokens[0].isNew && third.text.tokens[0].itemId == "c:vorrei")
        #expect(third.tokenTimings[0] == PackTokenTiming(line: 3, index: 0, startMs: 3_400, endMs: 3_700))
        #expect(story.itemIds == ["c:vorrei", "w:cappuccino", "c:per-favore"])
        let timeline = story.timeline
        #expect(timeline.count == 13)
        #expect(timeline.map(\.startMs) == timeline.map(\.startMs).sorted())
        #expect(timeline.first == PackTokenTiming(line: 1, index: 0, startMs: 0, endMs: 300))
    }

    @Test func textsInOrderAndErrors() async throws {
        let texts = try await reader.texts(["u02.l2.phone", "u02.l1.story"])
        #expect(texts.map(\.id) == ["u02.l2.phone", "u02.l1.story"])
        #expect(texts[0].audioId == nil && texts[0].timeline.isEmpty && texts[0].titleIt == nil)
        await #expect(throws: PackError.notFound(table: "texts", id: "u02.nope")) { try await reader.text("u02.nope") }
    }

    @Test func tokensOfAMissingLineAreAMalformedText() async throws {
        let reader = try PackReader(url: try TestPack.build { db in
            try db.execute(sql: """
                INSERT INTO tokens (text_id, line_ord, ord, surface, trailing, kind) \
                VALUES ('u02.l2.phone', 7, 1, 'x', '', 'word')
                """)
        })
        await #expect(throws: PackError.malformedRow(table: "tokens", id: "u02.l2.phone#7", reason: "no such line")) {
            try await reader.text("u02.l2.phone")
        }
    }

    @Test func audioLookupAndTimelines() async throws {
        let audio = try #require(try await reader.audio("a:000000000001"))
        #expect(audio.file == "000000000001.m4a" && audio.durationMs == 5_000 && audio.voice == "it-IT-A")
        #expect(audio.fileURL == reader.audioDirectory.appendingPathComponent("000000000001.m4a"))
        #expect(try await reader.audio("a:ffffffffffff") == nil)

        let story = try await reader.text("u02.l1.story")
        #expect(try await reader.timeline(forAudio: "a:000000000001") == story.timeline)
        #expect(try await reader.timeline(forAudio: "a:000000000002").isEmpty)  // item audio

        let catalog = try await reader.audioCatalog()
        #expect(catalog.audio.count == 3 && catalog.audio("a:000000000002")?.durationMs == 800)
        #expect(catalog.timeline("a:000000000001") == story.timeline)
        #expect(catalog.timeline("a:000000000003") == [PackTokenTiming(line: 1, index: 0, startMs: 0, endMs: 500)])
        #expect(catalog.textAudio == ["u02.l1.story": "a:000000000001", "u02.check.01.audio": "a:000000000003"])
        #expect(catalog.audioID(forText: "u02.check.01.audio") == "a:000000000003")
        #expect(catalog.audioID(forText: "u02.l2.phone") == nil)
        #expect(catalog.textID(forAudio: "a:000000000001") == "u02.l1.story")
        #expect(catalog.textID(forAudio: "a:000000000002") == nil)
        #expect(catalog.timeline("a:000000000002").isEmpty && PackAudioCatalog.empty.audio.isEmpty)
    }

    // MARK: People and places

    @Test func charactersCountriesAndExamples() async throws {
        #expect(try await reader.characters().map(\.id).contains("ch:narrator"))
        #expect(try await reader.character("ch:giulia").name == "Giulia")
        let countries = try await reader.countries()
        #expect(countries.map(\.id) == ["ca", "us"])  // by English name
        let us = try await reader.country("us")
        #expect(us.altHomePhrasesIt == ["in America"] && us.profileCountry.homePhrase == "negli Stati Uniti")
        await #expect(throws: PackError.notFound(table: "countries", id: "xx")) { try await reader.country("xx") }

        let examples = try await reader.learnerExamples()
        #expect(examples.nameM == "Marco" && examples.nameF == "Sara")
        #expect(examples.country.id == "ca" && examples.country.homePhrase == "in Canada")
    }

    // MARK: Malformed rows

    @Test func aPayloadThatContradictsItsRowIsMalformed() async throws {
        let reader = try PackReader(url: try TestPack.build { db in
            try db.execute(sql: "UPDATE exercises SET role = 'check' WHERE id = 'u02.l1.ex04'")
            try db.execute(sql: "UPDATE steps SET kind = 'reading' WHERE id = 'u02.l1.step-story'")
            try db.execute(sql: "UPDATE exercises SET payload = '{\"id\": 1' WHERE id = 'u02.l1.ex10'")
        })
        await #expect { try await reader.exercise("u02.l1.ex04") } throws: { error in
            guard case PackError.malformedRow("exercises", "u02.l1.ex04", let reason) = error else { return false }
            return reason.contains("role")
        }
        await #expect { try await reader.step("u02.l1.step-story") } throws: { error in
            guard case PackError.malformedRow("steps", "u02.l1.step-story", let reason) = error else { return false }
            return reason.contains("kind")
        }
        await #expect { try await reader.exercise("u02.l1.ex10") } throws: { error in
            guard case PackError.malformedRow("exercises", "u02.l1.ex10", let reason) = error else { return false }
            return reason.hasPrefix("payload")
        }
    }

    @Test func aMissingRequiredPayloadKeyIsMalformed() async throws {
        let reader = try PackReader(url: try TestPack.build { db in
            try db.execute(sql: "UPDATE exercises SET payload = json_remove(payload, '$.gap') WHERE id = 'u02.l1.ex01'")
        })
        await #expect { try await reader.exercise("u02.l1.ex01") } throws: { error in
            guard case PackError.malformedRow("exercises", "u02.l1.ex01", let reason) = error else { return false }
            return reason.contains("gap")
        }
    }

    // MARK: Concurrency

    @Test func concurrentQueriesFromManyTasks() async throws {
        let reader = reader
        let counts = try await withThrowingTaskGroup(of: Int.self) { group in
            for i in 0..<40 {
                group.addTask {
                    switch i % 4 {
                    case 0: try await reader.exercises(forStep: "u02.l1.step-practice").count
                    case 1: try await reader.text("u02.l1.story").lines.count
                    case 2: try await reader.contentIndex().steps.count
                    default: try await reader.allItems().count
                    }
                }
            }
            return try await group.reduce(into: [Int]()) { $0.append($1) }
        }
        #expect(counts.count == 40)
        #expect(Set(counts) == [4, 3, 15, 12])
    }
}
