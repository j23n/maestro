import Foundation
import GRDB
import LearningCore

// The typed queries (docs/02 § Storage). Every method runs on the pack's queue and returns values; a missing row
// throws `PackError.notFound` unless the method says it returns nil.

// MARK: - Course, units, lessons, steps

extension PackReader {
    /// Every unit in course order.
    public func units() async throws(PackError) -> [PackUnit] {
        try await read { db in try db.packRows(PackSQL.units).map(PackRows.unit) }
    }

    public func unit(_ id: UnitID) async throws(PackError) -> PackUnit {
        try await read { db in try Self.unit(db, id) }
    }

    /// Every can-do, by unit order then `ord`.
    public func canDos() async throws(PackError) -> [PackCanDo] {
        try await read { db in try db.packRows(PackSQL.canDos).map(PackRows.canDo) }
    }

    public func canDos(inUnit unit: UnitID) async throws(PackError) -> [PackCanDo] {
        try await read { db in try db.packRows(PackSQL.canDosInUnit, [unit.rawValue]).map(PackRows.canDo) }
    }

    public func lessons(inUnit unit: UnitID) async throws(PackError) -> [PackLesson] {
        try await read { db in try db.packRows(PackSQL.lessonsInUnit, [unit.rawValue]).map(PackRows.lesson) }
    }

    public func lesson(_ id: LessonID) async throws(PackError) -> PackLesson {
        try await read { db in
            guard let row = try db.packRow(PackSQL.lesson, [id.rawValue]) else {
                throw PackError.notFound(table: "lessons", id: id.rawValue)
            }
            return try PackRows.lesson(row)
        }
    }

    /// Every step of the course in course order `(units.ord, steps.ord)`.
    public func steps() async throws(PackError) -> [PackStep] {
        try await read { db in try db.packRows(PackSQL.steps).map(PackRows.step) }
    }

    /// The unit's steps in order: opener, the lessons' steps, task steps, check, fluency (docs/06 § Unit-level steps).
    public func steps(inUnit unit: UnitID) async throws(PackError) -> [PackStep] {
        try await read { db in try db.packRows(PackSQL.stepsInUnit, [unit.rawValue]).map(PackRows.step) }
    }

    public func steps(inLesson lesson: LessonID) async throws(PackError) -> [PackStep] {
        try await read { db in try db.packRows(PackSQL.stepsInLesson, [lesson.rawValue]).map(PackRows.step) }
    }

    public func step(_ id: StepID) async throws(PackError) -> PackStep {
        try await read { db in try Self.step(db, id) }
    }

    /// One unit with its can-dos, lessons and steps (Unit overview, opener).
    public func unitOutline(_ id: UnitID) async throws(PackError) -> PackUnitOutline {
        try await read { db in
            PackUnitOutline(
                unit: try Self.unit(db, id),
                canDos: try db.packRows(PackSQL.canDosInUnit, [id.rawValue]).map(PackRows.canDo),
                lessons: try db.packRows(PackSQL.lessonsInUnit, [id.rawValue]).map(PackRows.lesson),
                steps: try db.packRows(PackSQL.stepsInUnit, [id.rawValue]).map(PackRows.step))
        }
    }

    /// Every unit's outline in course order (Course / Indice).
    public func courseOutline() async throws(PackError) -> [PackUnitOutline] {
        try await read { db in
            let units = try db.packRows(PackSQL.units).map(PackRows.unit)
            let canDos = Dictionary(grouping: try db.packRows(PackSQL.canDos).map(PackRows.canDo), by: \.unitId)
            let lessons = Dictionary(grouping: try db.packRows(PackSQL.lessons).map(PackRows.lesson), by: \.unitId)
            let steps = Dictionary(grouping: try db.packRows(PackSQL.steps).map(PackRows.step), by: \.unitId)
            return units.map {
                PackUnitOutline(unit: $0, canDos: canDos[$0.id] ?? [], lessons: lessons[$0.id] ?? [],
                                steps: steps[$0.id] ?? [])
            }
        }
    }

    static func unit(_ db: Database, _ id: UnitID) throws -> PackUnit {
        guard let row = try db.packRow(PackSQL.unit, [id.rawValue]) else {
            throw PackError.notFound(table: "units", id: id.rawValue)
        }
        return try PackRows.unit(row)
    }

    static func step(_ db: Database, _ id: StepID) throws -> PackStep {
        guard let row = try db.packRow(PackSQL.step, [id.rawValue]) else {
            throw PackError.notFound(table: "steps", id: id.rawValue)
        }
        return try PackRows.step(row)
    }
}

// MARK: - Exercises, notes, assessments

extension PackReader {
    public func exercise(_ id: ExerciseID) async throws(PackError) -> PackExercise {
        try await read { db in try Self.exercise(db, id) }
    }

    /// The exercises in the order given (all of them, or `notFound` for the first missing one). Generated review
    /// cards (`gen:…`) are built at runtime and are never in the pack.
    public func exercises(_ ids: [ExerciseID]) async throws(PackError) -> [PackExercise] {
        try await read { db in try ids.map { try Self.exercise(db, $0) } }
    }

    /// The step's exercises in presentation order (`StepPayload.exerciseOrder`: a practice mix is shuffled with
    /// the step ID as seed, so every device resumes at the same exercise).
    public func exercises(forStep id: StepID) async throws(PackError) -> [PackExercise] {
        try await read { db in try Self.step(db, id).exerciseOrder.map { try Self.exercise(db, $0) } }
    }

    /// Bank exercises whose targets include the pair (review card candidates, docs/05 § Review session builder).
    public func exerciseIDs(targeting pair: ItemSkillPair) async throws(PackError) -> [ExerciseID] {
        try await read { db in
            try db.packRows(PackSQL.exercisesTargeting, [pair.itemId.rawValue, pair.skill.rawValue]).map { row in
                ExerciseID(try PackRow(row, table: "exercise_targets", id: pair.description).string("exercise_id"))
            }
        }
    }

    public func note(_ id: NoteID) async throws(PackError) -> PackNote {
        try await read { db in
            guard let row = try db.packRow(PackSQL.note, [id.rawValue]) else {
                throw PackError.notFound(table: "grammar_notes", id: id.rawValue)
            }
            let grammar = try db.packRows(PackSQL.noteItems, [id.rawValue]).map { r in
                ItemID(try PackRow(r, table: "note_items", id: id.rawValue).string("item_id"))
            }
            return try PackRows.note(row, grammar: grammar)
        }
    }

    /// The notes that introduce a grammar point (Words detail: "see the note").
    public func noteIDs(introducing item: ItemID) async throws(PackError) -> [NoteID] {
        try await read { db in
            try db.packRows(PackSQL.notesForItem, [item.rawValue]).map { r in
                NoteID(try PackRow(r, table: "note_items", id: item.rawValue).string("note_id"))
            }
        }
    }

    /// The placement blocks or the final-check sections; nil when this pack has none (a partial beta pack).
    public func assessment(_ kind: PackAssessmentKind) async throws(PackError) -> AssessmentPayload? {
        try await read { db in try db.packRow(PackSQL.assessment, [kind.rawValue]).map(PackRows.assessment) }
    }

    static func exercise(_ db: Database, _ id: ExerciseID) throws -> PackExercise {
        guard let row = try db.packRow(PackSQL.exercise, [id.rawValue]) else {
            throw PackError.notFound(table: "exercises", id: id.rawValue)
        }
        return try PackRows.exercise(row)
    }
}

// MARK: - Items, forms, sounds

extension PackReader {
    public func item(_ id: ItemID) async throws(PackError) -> PackItem {
        try await read { db in
            guard let row = try db.packRow(PackSQL.item, [id.rawValue]) else {
                throw PackError.notFound(table: "items", id: id.rawValue)
            }
            return try Self.items(db, [row])[0]
        }
    }

    /// The items in the order given (`notFound` for the first missing one).
    public func items(_ ids: [ItemID]) async throws(PackError) -> [PackItem] {
        try await read { db in
            let rows = try ids.map { id in
                guard let row = try db.packRow(PackSQL.item, [id.rawValue]) else {
                    throw PackError.notFound(table: "items", id: id.rawValue)
                }
                return row
            }
            return try Self.items(db, rows)
        }
    }

    /// The items a unit introduces, by ID.
    public func items(inUnit unit: UnitID) async throws(PackError) -> [PackItem] {
        try await read { db in try Self.items(db, try db.packRows(PackSQL.itemsInUnit, [unit.rawValue])) }
    }

    /// Every item, by ID.
    public func allItems() async throws(PackError) -> [PackItem] {
        try await read { db in try Self.allItems(db) }
    }

    /// The surface forms of one item that occur in course content.
    public func forms(of item: ItemID) async throws(PackError) -> [PackForm] {
        try await read { db in
            try db.packRows(PackSQL.formsOfItem, [item.rawValue]).map { row in
                let r = PackRow(row, table: "forms", id: item.rawValue)
                return PackForm(form: try r.string("form"), itemId: try r.id("item_id"), morph: try r.string("morph"))
            }
        }
    }

    /// The `forms` table as the graders need it (`TypedAnswerGrader(knownForms:profile:)`, writing suggestions).
    public func knownForms() async throws(PackError) -> KnownForms {
        try await read { db in try Self.knownForms(db) }
    }

    /// A sound item's minimal pairs (`sounds.pairs`); empty for an item without pairs.
    public func soundPairs(of item: ItemID) async throws(PackError) -> [[ContentIndex.SoundWord]] {
        try await read { db in try db.packRow(PackSQL.sound, [item.rawValue]).map(PackRows.sounds) ?? [] }
    }

    /// The Words screen's search index over every item (see `PackSearchIndex`).
    public func searchIndex() async throws(PackError) -> PackSearchIndex {
        try await read { db in
            let units = try db.packRows(PackSQL.units).map(PackRows.unit)
            var forms: [ItemID: [String]] = [:]
            for row in try db.packRows(PackSQL.forms) {
                let r = PackRow(row, table: "forms", id: "?")
                forms[try r.id("item_id"), default: []].append(try r.string("form"))
            }
            return PackSearchIndex(items: try Self.allItems(db), forms: forms,
                                   unitOrder: Dictionary(uniqueKeysWithValues: units.map { ($0.id, $0.ord) }))
        }
    }

    /// Item rows with their skills and requirements, looked up per item.
    static func items(_ db: Database, _ rows: [Row]) throws -> [PackItem] {
        try rows.map { row in
            let id = (try? row.decode(String.self, forColumn: "id")) ?? "?"
            var skills: [Skill: ContentIndex.SkillInfo] = [:]
            for s in try db.packRows(PackSQL.itemSkills, [id]) {
                let (skill, info) = try PackRows.skill(s, item: id)
                skills[skill] = info
            }
            let requires = try db.packRows(PackSQL.itemRequires, [id]).map { r in
                ItemID(try PackRow(r, table: "item_requires", id: id).string("requires_id"))
            }
            return try PackRows.item(row, skills: skills, requires: requires)
        }
    }

    /// Every item, with skills and requirements loaded in two table scans.
    static func allItems(_ db: Database) throws -> [PackItem] {
        var skills: [String: [Skill: ContentIndex.SkillInfo]] = [:]
        for row in try db.packRows(PackSQL.allItemSkills) {
            let id = try PackRow(row, table: "item_skills", id: "?").string("item_id")
            let (skill, info) = try PackRows.skill(row, item: id)
            skills[id, default: [:]][skill] = info
        }
        var requires: [String: [ItemID]] = [:]
        for row in try db.packRows(PackSQL.allItemRequires) {
            let r = PackRow(row, table: "item_requires", id: "?")
            requires[try r.string("item_id"), default: []].append(ItemID(try r.string("requires_id")))
        }
        return try db.packRows(PackSQL.items).map { row in
            let id = (try? row.decode(String.self, forColumn: "id")) ?? "?"
            return try PackRows.item(row, skills: skills[id] ?? [:], requires: requires[id] ?? [])
        }
    }

    static func knownForms(_ db: Database) throws -> KnownForms {
        let rows: [(form: String, itemID: ItemID)] = try db.packRows(PackSQL.forms).map { row in
            let r = PackRow(row, table: "forms", id: "?")
            return (form: try r.string("form"), itemID: ItemID(try r.string("item_id")))
        }
        return KnownForms(rows: rows)
    }
}

// MARK: - Texts and audio

extension PackReader {
    /// A text with its lines, tokens and timings; real-world texts carry their layout.
    public func text(_ id: TextID) async throws(PackError) -> PackText {
        try await read { db in try Self.text(db, id) }
    }

    /// The texts in the order given (a fluency step's stories).
    public func texts(_ ids: [TextID]) async throws(PackError) -> [PackText] {
        try await read { db in try ids.map { try Self.text(db, $0) } }
    }

    /// An audio row, or nil when the pack has none with this ID (then there is no play button, docs/09).
    public func audio(_ id: AudioID) async throws(PackError) -> PackAudio? {
        let directory = audioDirectory
        return try await read { db in
            try db.packRow(PackSQL.audio, [id.rawValue]).map { row throws(PackError) in
                try PackRows.audio(row, directory: directory)
            }
        }
    }

    /// The read-along timeline of the text whose audio this is; empty for item and exercise audio.
    public func timeline(forAudio id: AudioID) async throws(PackError) -> [PackTokenTiming] {
        try await read { db in
            guard let row = try db.packRow(PackSQL.textForAudio, [id.rawValue]) else { return [] }
            let textID = TextID(try PackRow(row, table: "texts").string("id"))
            return try Self.text(db, textID).timeline
        }
    }

    /// Every audio row and text timeline, for synchronous lookups (load once, keep it).
    public func audioCatalog() async throws(PackError) -> PackAudioCatalog {
        let directory = audioDirectory
        return try await read { db in
            var audio: [AudioID: PackAudio] = [:]
            for row in try db.packRows(PackSQL.allAudio) {
                let a = try PackRows.audio(row, directory: directory)
                audio[a.id] = a
            }
            var textAudio: [TextID: AudioID] = [:]
            for row in try db.packRows(PackSQL.textAudio) {
                let r = PackRow(row, table: "texts")
                textAudio[TextID(r.id)] = try r.id("audio_id")
            }
            let catalog = PackAudioCatalog(audio: audio, timelines: [:], textAudio: textAudio)
            var timelines: [AudioID: [PackTokenTiming]] = [:]
            var position: (text: String, line: Int, index: Int)?
            for row in try db.packRows(PackSQL.audioTokens) {
                let r = PackRow(row, table: "tokens", id: "?")
                let text = try r.string("text_id")
                let line = try r.int("line_ord")
                let audioID: AudioID = try r.id("audio_id")
                let index = position.map { $0.text == text && $0.line == line ? $0.index + 1 : 0 } ?? 0
                position = (text, line, index)
                guard catalog.textID(forAudio: audioID)?.rawValue == text else { continue }  // one text per file
                guard let start = try r.optInt("start_ms"), let end = try r.optInt("end_ms") else { continue }
                timelines[audioID, default: []].append(
                    PackTokenTiming(line: line, index: index, startMs: start, endMs: end))
            }
            for (id, timeline) in timelines {
                timelines[id] = timeline.sorted { ($0.startMs, $0.line, $0.index) < ($1.startMs, $1.line, $1.index) }
            }
            return PackAudioCatalog(audio: audio, timelines: timelines, textAudio: textAudio)
        }
    }

    static func text(_ db: Database, _ id: TextID) throws -> PackText {
        guard let row = try db.packRow(PackSQL.text, [id.rawValue]) else {
            throw PackError.notFound(table: "texts", id: id.rawValue)
        }
        let r = PackRow(row, table: "texts")
        var tokens: [Int: [(token: PackToken, start: Int?, end: Int?)]] = [:]
        for t in try db.packRows(PackSQL.textTokens, [id.rawValue]) {
            let line = try PackRow(t, table: "tokens", id: id.rawValue).int("line_ord")
            let tr = PackRow(t, table: "tokens", id: "\(id.rawValue)#\(line)")
            let token = PackToken(
                surface: try tr.string("surface"), trailing: try tr.string("trailing"), kind: try tr.enumValue("kind"),
                itemId: try tr.optID("item_id"), gloss: try tr.optString("gloss_en"), flags: try tr.int("flags"))
            tokens[line, default: []].append((token, try tr.optInt("start_ms"), try tr.optInt("end_ms")))
        }
        var lines: [PackTextLine] = []
        for l in try db.packRows(PackSQL.textLines, [id.rawValue]) {
            let number = try PackRow(l, table: "text_lines", id: id.rawValue).int("ord")
            let lr = PackRow(l, table: "text_lines", id: "\(id.rawValue)#\(number)")
            let it = try lr.string("it")
            let lineTokens = tokens.removeValue(forKey: number) ?? []
            let timings = lineTokens.enumerated().map { i, t -> PackTokenTiming? in
                guard let start = t.start, let end = t.end else { return nil }
                return PackTokenTiming(line: number, index: i, startMs: start, endMs: end)
            }
            lines.append(PackTextLine(
                number: number, speakerId: try lr.optID("speaker_id"), addresseeId: try lr.optID("addressee_id"),
                register: try lr.optEnum("register"),
                text: TokenizedText(text: it, lead: Self.lead(of: it, tokens: lineTokens.map(\.token)),
                                    tokens: lineTokens.map(\.token)),
                en: try lr.string("en"), startMs: try lr.optInt("start_ms"), endMs: try lr.optInt("end_ms"),
                tokenTimings: timings))
        }
        if let orphan = tokens.keys.min() {
            throw PackError.malformedRow(table: "tokens", id: "\(id.rawValue)#\(orphan)", reason: "no such line")
        }
        return PackText(
            id: id, unitId: try r.id("unit_id"), kind: try r.enumValue("kind"), titleIt: try r.optString("title_it"),
            titleEn: try r.optString("title_en"), layout: try r.optJSON("layout"), audioId: try r.optID("audio_id"),
            durationMs: try r.optInt("duration_ms"), lines: lines)
    }

    /// What precedes the first token (an opening quote), so `lead + Σ(surface + trailing) == text`.
    static func lead(of text: String, tokens: [PackToken]) -> String {
        let rebuilt = tokens.map { $0.surface + $0.trailing }.joined()
        guard text.hasSuffix(rebuilt) else { return "" }
        return String(text.dropLast(rebuilt.count))
    }
}

// MARK: - Characters, countries

extension PackReader {
    public func characters() async throws(PackError) -> [PackCharacter] {
        try await read { db in try db.packRows(PackSQL.characters).map(PackRows.character) }
    }

    public func character(_ id: CharacterID) async throws(PackError) -> PackCharacter {
        try await read { db in try Self.character(db, id) }
    }

    /// Every country, by English name (onboarding shows the Italian names).
    public func countries() async throws(PackError) -> [PackCountry] {
        try await read { db in try db.packRows(PackSQL.countries).map(PackRows.country) }
    }

    public func country(_ id: String) async throws(PackError) -> PackCountry {
        try await read { db in try Self.country(db, id) }
    }

    /// The characters and country whose names model answers use when the learner gave none (docs/03 § Personal
    /// slots): `ch:marco` (masculine or both forms), `ch:sara` (feminine) and Marco's country `ca`.
    public static let exampleNameM: CharacterID = "ch:marco"
    public static let exampleNameF: CharacterID = "ch:sara"
    public static let exampleCountry = "ca"

    /// The examples for `LearnerProfile.Examples`, from the pack so no Italian is hard-coded in Swift.
    public func learnerExamples() async throws(PackError) -> LearnerProfile.Examples {
        try await read { db in
            LearnerProfile.Examples(
                nameM: try Self.character(db, Self.exampleNameM).name,
                nameF: try Self.character(db, Self.exampleNameF).name,
                country: try Self.country(db, Self.exampleCountry).profileCountry)
        }
    }

    static func character(_ db: Database, _ id: CharacterID) throws -> PackCharacter {
        guard let row = try db.packRow(PackSQL.character, [id.rawValue]) else {
            throw PackError.notFound(table: "characters", id: id.rawValue)
        }
        return try PackRows.character(row)
    }

    static func country(_ db: Database, _ id: String) throws -> PackCountry {
        guard let row = try db.packRow(PackSQL.country, [id]) else {
            throw PackError.notFound(table: "countries", id: id)
        }
        return try PackRows.country(row)
    }
}
