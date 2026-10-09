import Foundation
import GRDB
import LearningCore

/// Every statement the reader runs. They are prepared once per connection (`cachedStatement`), and all of them are
/// prepared when the pack opens, so a pack whose tables don't fit fails at open rather than on some later screen.
/// Each lookup uses a primary key or an index of `schemas/content-pack.sql`, except the tiny tables (`units`,
/// `can_dos`, `characters`, `countries`, `texts` by audio) and the whole-table loads.
enum PackSQL {
    static let unitColumns = "id, ord, title_it, title_en, episode_en, est_minutes, kind"
    static let units = "SELECT \(unitColumns) FROM units ORDER BY ord"
    static let unit = "SELECT \(unitColumns) FROM units WHERE id = ?"

    static let canDoColumns = "c.id, c.unit_id, c.ord, c.text_en, c.cefr_scale, c.stretch"
    static let canDos =
        "SELECT \(canDoColumns) FROM can_dos c JOIN units u ON u.id = c.unit_id ORDER BY u.ord, c.ord, c.id"
    static let canDosInUnit = "SELECT \(canDoColumns) FROM can_dos c WHERE c.unit_id = ? ORDER BY c.ord, c.id"

    static let lessonColumns = "l.id, l.unit_id, l.ord, l.title_it, l.title_en, l.est_minutes"
    static let lessons = "SELECT \(lessonColumns) FROM lessons l JOIN units u ON u.id = l.unit_id ORDER BY u.ord, l.ord"
    static let lessonsInUnit = "SELECT \(lessonColumns) FROM lessons l WHERE l.unit_id = ? ORDER BY l.ord"
    static let lesson = "SELECT \(lessonColumns) FROM lessons l WHERE l.id = ?"

    static let stepColumns =
        "s.id, s.unit_id, s.lesson_id, s.ord, s.kind, s.title_en, s.payload, s.est_seconds, s.strand, s.draft"
    static let steps = "SELECT \(stepColumns) FROM steps s JOIN units u ON u.id = s.unit_id ORDER BY u.ord, s.ord"
    static let stepsInUnit = "SELECT \(stepColumns) FROM steps s WHERE s.unit_id = ? ORDER BY s.ord"
    static let stepsInLesson = "SELECT \(stepColumns) FROM steps s WHERE s.lesson_id = ? ORDER BY s.ord"
    static let step = "SELECT \(stepColumns) FROM steps s WHERE s.id = ?"
    static let stepIntroduces = "SELECT step_id, item_id, skill FROM step_introduces ORDER BY step_id, item_id, skill"

    static let exerciseColumns = "id, format, unit_id, step_id, role, payload, score, est_seconds, source_ref"
    static let exercise = "SELECT \(exerciseColumns) FROM exercises WHERE id = ?"
    static let allExercisePayloads = "SELECT \(exerciseColumns) FROM exercises ORDER BY id"
    static let exerciseHeads =
        "SELECT id, format, unit_id, step_id, role, score, est_seconds FROM exercises ORDER BY id"
    static let exercisesTargeting =
        "SELECT exercise_id FROM exercise_targets WHERE item_id = ? AND skill = ? ORDER BY exercise_id"
    static let matchPayloads = "SELECT id, payload FROM exercises WHERE format = 'match' ORDER BY id"
    static let exerciseTargets = "SELECT exercise_id, item_id, skill FROM exercise_targets"
    static let exerciseRequires = "SELECT exercise_id, item_id, skill FROM exercise_requires"
    static let exerciseTags = "SELECT exercise_id, tag FROM exercise_tags ORDER BY exercise_id, tag"

    static let noteColumns = "id, unit_id, step_id, title_en, body"
    static let note = "SELECT \(noteColumns) FROM grammar_notes WHERE id = ?"
    static let noteHeads = "SELECT id, step_id FROM grammar_notes ORDER BY id"
    static let allNotes = "SELECT \(noteColumns) FROM grammar_notes ORDER BY id"
    static let noteItems = "SELECT item_id FROM note_items WHERE note_id = ? ORDER BY ord, item_id"
    static let allNoteItems = "SELECT note_id, item_id FROM note_items ORDER BY note_id, ord, item_id"
    static let notesForItem = "SELECT note_id FROM note_items WHERE item_id = ? ORDER BY note_id"

    static let assessment = "SELECT id, payload FROM assessments WHERE id = ?"
    static let assessments = "SELECT id, payload FROM assessments ORDER BY id"

    static let itemColumns = """
        id, kind, it, display_indef, display_def, recall_answer, gloss_en, alt_glosses_en, note_en, pos, gender, \
        plural, unit_id, lesson_id, topics, audio_id, flags
        """
    static let item = "SELECT \(itemColumns) FROM items WHERE id = ?"
    static let items = "SELECT \(itemColumns) FROM items ORDER BY id"
    static let itemsInUnit = "SELECT \(itemColumns) FROM items WHERE unit_id = ? ORDER BY id"
    static let itemSkills = "SELECT skill, status, scheduled FROM item_skills WHERE item_id = ?"
    static let allItemSkills = "SELECT item_id, skill, status, scheduled FROM item_skills"
    static let itemRequires = "SELECT requires_id FROM item_requires WHERE item_id = ? ORDER BY requires_id"
    static let allItemRequires = "SELECT item_id, requires_id FROM item_requires ORDER BY item_id, requires_id"
    static let formsOfItem = "SELECT form, item_id, morph FROM forms WHERE item_id = ? ORDER BY form, morph"
    static let forms = "SELECT form, item_id FROM forms"
    /// Letter items (spoken spelling, docs/05 § Speech transcripts): each letter with the name its item says.
    static let letterNames = "SELECT id, letter, it FROM items WHERE letter IS NOT NULL ORDER BY letter"
    /// The forms of every item that isn't a letter item: a letter's name among them is also an ordinary word (CL41).
    static let wordForms = """
        SELECT DISTINCT form FROM forms WHERE item_id NOT IN (SELECT id FROM items WHERE letter IS NOT NULL) \
        ORDER BY form
        """
    static let sound = "SELECT item_id, pairs FROM sounds WHERE item_id = ?"
    static let sounds = "SELECT item_id, pairs FROM sounds ORDER BY item_id"

    static let textColumns = "id, unit_id, kind, title_it, title_en, layout, audio_id, duration_ms"
    static let text = "SELECT \(textColumns) FROM texts WHERE id = ?"
    static let allTexts = "SELECT \(textColumns) FROM texts ORDER BY id"
    static let textHeads = "SELECT id, unit_id, kind, audio_id FROM texts ORDER BY id"
    static let textAudio = "SELECT id, audio_id FROM texts WHERE audio_id IS NOT NULL ORDER BY id"
    static let textForAudio = "SELECT id FROM texts WHERE audio_id = ? ORDER BY id LIMIT 1"
    static let textLines = """
        SELECT ord, speaker_id, addressee_id, register, it, en, start_ms, end_ms FROM text_lines \
        WHERE text_id = ? ORDER BY ord
        """
    static let textTokens = """
        SELECT line_ord, ord, surface, trailing, kind, item_id, gloss_en, flags, start_ms, end_ms FROM tokens \
        WHERE text_id = ? ORDER BY line_ord, ord
        """
    static let audioTokens = """
        SELECT t.audio_id, k.text_id, k.line_ord, k.start_ms, k.end_ms FROM tokens k JOIN texts t ON t.id = k.text_id \
        WHERE t.audio_id IS NOT NULL ORDER BY k.text_id, k.line_ord, k.ord
        """
    static let textRequires = "SELECT text_id, item_id, skill FROM text_requires"

    static let audioColumns = "id, file, duration_ms, voice, sha256"
    static let audio = "SELECT \(audioColumns) FROM audio WHERE id = ?"
    static let allAudio = "SELECT \(audioColumns) FROM audio ORDER BY id"

    static let characters = "SELECT id, name, description_en FROM characters ORDER BY id"
    static let character = "SELECT id, name, description_en FROM characters WHERE id = ?"
    static let countryColumns =
        "id, name_en, name_it, home_phrase_it, alt_home_phrases_it, nationality_m, nationality_f"
    static let countries = "SELECT \(countryColumns) FROM countries ORDER BY name_en, id"
    static let country = "SELECT \(countryColumns) FROM countries WHERE id = ?"

    /// Prepared at open.
    static let all: [String] = [
        units, unit, canDos, canDosInUnit, lessons, lessonsInUnit, lesson, steps, stepsInUnit, stepsInLesson, step,
        stepIntroduces, exercise, allExercisePayloads, exerciseHeads, exercisesTargeting, matchPayloads,
        exerciseTargets, exerciseRequires, exerciseTags, note, noteHeads, allNotes, noteItems, allNoteItems,
        notesForItem, assessment, assessments, item, items, itemsInUnit, itemSkills, allItemSkills, itemRequires,
        allItemRequires, formsOfItem, forms, letterNames, wordForms, sound, sounds, text, allTexts, textHeads,
        textAudio, textForAudio, textLines, textTokens, audioTokens, textRequires, audio, allAudio, characters,
        character, countries, country,
    ]
}

/// Row → value mappers. Each one decodes its JSON and checks it against the row's columns.
enum PackRows {
    static func unit(_ row: Row) throws(PackError) -> PackUnit {
        let r = PackRow(row, table: "units")
        return PackUnit(
            id: try r.id("id"), ord: try r.int("ord"), titleIt: try r.string("title_it"),
            titleEn: try r.string("title_en"), episodeEn: try r.string("episode_en"),
            estMinutes: try r.int("est_minutes"), kind: try r.enumValue("kind"))
    }

    static func canDo(_ row: Row) throws(PackError) -> PackCanDo {
        let r = PackRow(row, table: "can_dos")
        return PackCanDo(
            id: try r.id("id"), unitId: try r.id("unit_id"), ord: try r.int("ord"), textEn: try r.string("text_en"),
            cefrScale: try r.optString("cefr_scale"), isStretch: try r.bool("stretch"))
    }

    static func lesson(_ row: Row) throws(PackError) -> PackLesson {
        let r = PackRow(row, table: "lessons")
        return PackLesson(
            id: try r.id("id"), unitId: try r.id("unit_id"), ord: try r.int("ord"), titleIt: try r.string("title_it"),
            titleEn: try r.string("title_en"), estMinutes: try r.int("est_minutes"))
    }

    static func step(_ row: Row) throws(PackError) -> PackStep {
        let r = PackRow(row, table: "steps")
        let kind: StepKind = try r.enumValue("kind")
        let payload: StepPayload = try r.json("payload")
        guard payload.kind == kind else {
            throw r.fail("payload kind \(payload.kind.rawValue) differs from the row's kind \(kind.rawValue)")
        }
        return PackStep(
            id: try r.id("id"), unitId: try r.id("unit_id"), lessonId: try r.optID("lesson_id"), ord: try r.int("ord"),
            kind: kind, titleEn: try r.optString("title_en"), payload: payload, estSeconds: try r.int("est_seconds"),
            strand: try r.enumValue("strand"), isDraft: try r.bool("draft"))
    }

    static func exercise(_ row: Row) throws(PackError) -> PackExercise {
        let r = PackRow(row, table: "exercises")
        let p: ExercisePayload = try r.json("payload")
        let format: ExerciseFormat = try r.enumValue("format")
        let role: ExerciseRole = try r.enumValue("role")
        let unitId = try r.string("unit_id")
        let stepId = try r.optString("step_id")
        let score = try r.int("score")
        var conflicts: [String] = []
        if p.id.rawValue != r.id { conflicts.append("id \(p.id)") }
        if p.format != format { conflicts.append("format") }
        if p.role != role { conflicts.append("role") }
        if p.unitId.rawValue != unitId { conflicts.append("unitId") }
        if p.stepId?.rawValue != stepId { conflicts.append("stepId") }
        if p.score != score { conflicts.append("score") }
        guard conflicts.isEmpty else {
            throw r.fail("payload differs from the row's columns: \(conflicts.joined(separator: ", "))")
        }
        return PackExercise(payload: p, estSeconds: try r.int("est_seconds"), sourceRef: try r.optString("source_ref"))
    }

    static func note(_ row: Row, grammar: [ItemID]) throws(PackError) -> PackNote {
        let r = PackRow(row, table: "grammar_notes")
        let body: NoteBody = try r.json("body")
        guard body.noteId.rawValue == r.id else { throw r.fail("body.noteId is \(body.noteId)") }
        return PackNote(
            id: try r.id("id"), unitId: try r.id("unit_id"), stepId: try r.id("step_id"),
            titleEn: try r.string("title_en"), body: body, grammar: grammar)
    }

    static func assessment(_ row: Row) throws(PackError) -> AssessmentPayload {
        let r = PackRow(row, table: "assessments")
        let payload: AssessmentPayload = try r.json("payload")
        let payloadID: String =
            switch payload {
            case .placement: "placement"
            case .final: "final"
            }
        guard payloadID == r.id else { throw r.fail("payload id is \(payloadID)") }
        return payload
    }

    static func item(_ row: Row, skills: [Skill: ContentIndex.SkillInfo], requires: [ItemID]) throws(PackError)
        -> PackItem
    {
        let r = PackRow(row, table: "items")
        return PackItem(
            id: try r.id("id"), kind: try r.enumValue("kind"), it: try r.string("it"),
            displayIndef: try r.optString("display_indef"), displayDef: try r.optString("display_def"),
            recallAnswer: try r.optString("recall_answer"), glossEn: try r.string("gloss_en"),
            altGlossesEn: try r.json("alt_glosses_en"), noteEn: try r.optString("note_en"), pos: try r.optString("pos"),
            gender: try r.optEnum("gender"), plural: try r.optString("plural"), unitId: try r.id("unit_id"),
            lessonId: try r.optID("lesson_id"), topics: try r.json("topics"), audioId: try r.optID("audio_id"),
            flags: try r.int("flags"), skills: skills, requires: requires)
    }

    /// One `item_skills` row (without its item ID column when read per item).
    static func skill(_ row: Row, item: String) throws(PackError) -> (Skill, ContentIndex.SkillInfo) {
        let r = PackRow(row, table: "item_skills", id: item)
        let info = ContentIndex.SkillInfo(status: try r.enumValue("status"), scheduled: try r.bool("scheduled"))
        return (try r.enumValue("skill"), info)
    }

    /// `sounds.pairs`: `[[{"it": "pena", "audioId": "a:…"}, …]]`; a bare word (`"pena"`, no audio yet) is accepted.
    static func sounds(_ row: Row) throws(PackError) -> [[ContentIndex.SoundWord]] {
        let r = PackRow(row, table: "sounds", id: (try? row.decode(String.self, forColumn: "item_id")) ?? "?")
        let pairs: [[SoundWordJSON]] = try r.json("pairs")
        return pairs.map { $0.map(\.word) }
    }

    private struct SoundWordJSON: Decodable {
        let word: ContentIndex.SoundWord

        init(from decoder: Decoder) throws {
            if let bare = try? decoder.singleValueContainer().decode(String.self) {
                word = ContentIndex.SoundWord(it: bare)
            } else {
                word = try ContentIndex.SoundWord(from: decoder)
            }
        }
    }

    static func audio(_ row: Row, directory: URL) throws(PackError) -> PackAudio {
        let r = PackRow(row, table: "audio")
        let file = try r.string("file")
        return PackAudio(
            id: try r.id("id"), file: file, fileURL: directory.appendingPathComponent(file),
            durationMs: try r.int("duration_ms"), voice: try r.string("voice"), sha256: try r.string("sha256"))
    }

    static func character(_ row: Row) throws(PackError) -> PackCharacter {
        let r = PackRow(row, table: "characters")
        return PackCharacter(
            id: try r.id("id"), name: try r.string("name"), descriptionEn: try r.string("description_en"))
    }

    static func country(_ row: Row) throws(PackError) -> PackCountry {
        let r = PackRow(row, table: "countries")
        return PackCountry(
            id: try r.string("id"), nameEn: try r.string("name_en"), nameIt: try r.string("name_it"),
            homePhraseIt: try r.string("home_phrase_it"), altHomePhrasesIt: try r.json("alt_home_phrases_it"),
            nationalityM: try r.string("nationality_m"), nationalityF: try r.string("nationality_f"))
    }

    /// An (item, skill) pair from a requirement, target or introduction row.
    static func itemSkill(_ row: Row, table: String, owner: String) throws(PackError) -> ItemSkillPair {
        let r = PackRow(row, table: table, id: (try? row.decode(String.self, forColumn: owner)) ?? "?")
        return ItemSkillPair(try r.id("item_id"), try r.enumValue("skill"))
    }
}
