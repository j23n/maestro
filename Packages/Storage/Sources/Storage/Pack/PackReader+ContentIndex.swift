import Foundation
import GRDB
import LearningCore

// The learning engine's view of the pack (LearningCore `ContentIndex`, docs/05): built in one read from the
// tables and the step and assessment payloads. Exercise payloads aren't decoded, except a match's `targets` (the
// table has no order column, and `targets[i]` belongs to `pairs[i]`).

extension PackReader {
    /// The `ContentIndex` for this pack. The pack never changes while the app runs: build it once and keep it.
    public func contentIndex() async throws(PackError) -> ContentIndex {
        let meta = meta
        return try await read { db in try Self.contentIndex(db, meta: meta) }
    }

    static func contentIndex(_ db: Database, meta: PackMeta) throws -> ContentIndex {
        let introduces = try pairs(db, PackSQL.stepIntroduces, table: "step_introduces", owner: "step_id")
        var steps: [ContentIndex.Step] = []
        var checks: [ContentIndex.Check] = []
        for row in try db.packRows(PackSQL.steps) {
            let step = try PackRows.step(row)
            let (indexed, check) = indexStep(step, introduces: introduces[step.id.rawValue] ?? [])
            steps.append(indexed)
            if let check { checks.append(check) }
        }

        let targets = try pairs(db, PackSQL.exerciseTargets, table: "exercise_targets", owner: "exercise_id")
        let requires = try pairs(db, PackSQL.exerciseRequires, table: "exercise_requires", owner: "exercise_id")
        let ordered = try matchTargets(db, table: targets)
        var tags: [String: [String]] = [:]
        for row in try db.packRows(PackSQL.exerciseTags) {
            let r = PackRow(row, table: "exercise_tags", id: "?")
            tags[try r.string("exercise_id"), default: []].append(try r.string("tag"))
        }
        let exercises = try db.packRows(PackSQL.exerciseHeads).map { row in
            let r = PackRow(row, table: "exercises")
            return ContentIndex.Exercise(
                id: ExerciseID(r.id), format: try r.enumValue("format"), unitId: try r.id("unit_id"),
                stepId: try r.optID("step_id"), role: try r.enumValue("role"), score: try r.int("score"),
                targets: ordered[r.id] ?? targets[r.id] ?? [], tags: tags[r.id] ?? [], requires: requires[r.id] ?? [])
        }

        let textRequires = try pairs(db, PackSQL.textRequires, table: "text_requires", owner: "text_id")
        let texts = try db.packRows(PackSQL.textHeads).map { row in
            let r = PackRow(row, table: "texts")
            return ContentIndex.Text(id: TextID(r.id), unitId: try r.id("unit_id"), requires: textRequires[r.id] ?? [])
        }

        var noteItems: [String: [ItemID]] = [:]
        for row in try db.packRows(PackSQL.allNoteItems) {
            let r = PackRow(row, table: "note_items", id: "?")
            noteItems[try r.string("note_id"), default: []].append(try r.id("item_id"))
        }
        let notes = try db.packRows(PackSQL.noteHeads).map { row in
            let r = PackRow(row, table: "grammar_notes")
            return ContentIndex.Note(id: NoteID(r.id), stepId: try r.id("step_id"), itemIds: noteItems[r.id] ?? [])
        }

        let sounds = try db.packRows(PackSQL.sounds).map { row in
            ContentIndex.Sound(
                itemId: ItemID(try PackRow(row, table: "sounds", id: "?").string("item_id")),
                pairs: try PackRows.sounds(row))
        }

        return ContentIndex(
            packVersion: meta.packVersion, contentHash: meta.contentHash,
            units: try db.packRows(PackSQL.units).map(PackRows.unit).map {
                ContentIndex.Unit(id: $0.id, ord: $0.ord, kind: $0.kind)
            },
            lessons: try db.packRows(PackSQL.lessons).map(PackRows.lesson).map {
                ContentIndex.Lesson(id: $0.id, unitId: $0.unitId, ord: $0.ord)
            },
            steps: steps, items: try allItems(db).map(\.indexItem), exercises: exercises, texts: texts, notes: notes,
            canDos: try db.packRows(PackSQL.canDos).map(PackRows.canDo).map {
                ContentIndex.CanDo(id: $0.id, unitId: $0.unitId, ord: $0.ord)
            },
            checks: checks, placement: try placement(db), finalCheck: try finalCheck(db), sounds: sounds)
    }

    /// A step row as the index holds it: what its payload references, and its check when it is one.
    static func indexStep(_ step: PackStep, introduces: [ItemSkillPair]) -> (ContentIndex.Step, ContentIndex.Check?) {
        var exerciseIds: [ExerciseID] = []
        var block: [ExerciseID] = []
        var mix: [ExerciseID] = []
        var noteId: NoteID?
        var check: ContentIndex.Check?
        switch step.payload {
        case .opener, .fluency: break
        case .preview(let batches): exerciseIds = batches.flatMap(\.exerciseIds)
        case .story(_, let questions): exerciseIds = questions
        case .listening(_, _, let ids), .reading(_, let ids), .sounds(let ids): exerciseIds = ids
        case .note(let id): noteId = id
        case .practice(let b, let m):
            block = b
            mix = m
        case .single(_, let id): exerciseIds = [id]
        case .check(let id, let pass, let sections):
            let indexed = sections.map { ContentIndex.CheckSection(id: $0.id, exerciseIds: $0.exerciseIds) }
            exerciseIds = indexed.flatMap(\.exerciseIds)
            check = ContentIndex.Check(
                id: CheckID(id), unitId: step.unitId, stepId: step.id, passOverall: pass.overall,
                sectionMin: pass.sectionMin, sections: indexed)
        }
        let indexed = ContentIndex.Step(
            id: step.id, unitId: step.unitId, lessonId: step.lessonId, ord: step.ord, kind: step.kind,
            strand: step.strand, exerciseIds: exerciseIds, block: block, mix: mix, textIds: step.textIds,
            noteId: noteId, checkId: check?.id, introduces: introduces)
        return (indexed, check)
    }

    /// The authored target order of every match exercise (its payload's `targets`), which must be the same pairs
    /// as its `exercise_targets` rows.
    private static func matchTargets(_ db: Database, table: [String: [ItemSkillPair]]) throws
        -> [String: [ItemSkillPair]]
    {
        struct Targets: Decodable { let targets: [TargetPayload] }
        var out: [String: [ItemSkillPair]] = [:]
        for row in try db.packRows(PackSQL.matchPayloads) {
            let r = PackRow(row, table: "exercises")
            let ordered = try r.json("payload", as: Targets.self).targets.map { ItemSkillPair($0.itemId, $0.skill) }
            guard ordered.sorted() == (table[r.id] ?? []) else {
                throw r.fail("payload targets differ from exercise_targets")
            }
            out[r.id] = ordered
        }
        return out
    }

    private static func placement(_ db: Database) throws -> ContentIndex.PlacementAssessment? {
        guard let row = try db.packRow(PackSQL.assessment, [PackAssessmentKind.placement.rawValue]),
            case .placement(let threshold, let blocks) = try PackRows.assessment(row)
        else { return nil }
        return ContentIndex.PlacementAssessment(
            advanceThreshold: Double(threshold),
            blocks: blocks.map {
                ContentIndex.PlacementAssessment.Block(unitId: $0.unitId, exerciseIds: $0.exerciseIds)
            })
    }

    private static func finalCheck(_ db: Database) throws -> ContentIndex.FinalAssessment? {
        guard let row = try db.packRow(PackSQL.assessment, [PackAssessmentKind.final.rawValue]),
            case .final(let pass, let sections) = try PackRows.assessment(row)
        else { return nil }
        return ContentIndex.FinalAssessment(
            sections: sections.map {
                ContentIndex.CheckSection(id: $0.id, exerciseIds: $0.exerciseIds, max: Double($0.max))
            },
            indicativePassPerSection: Double(pass))
    }

    /// `(owner, item_id, skill)` rows grouped by owner, each group sorted.
    static func pairs(_ db: Database, _ sql: String, table: String, owner: String) throws -> [String: [ItemSkillPair]] {
        var out: [String: [ItemSkillPair]] = [:]
        for row in try db.packRows(sql) {
            let key = try PackRow(row, table: table, id: "?").string(owner)
            out[key, default: []].append(try PackRows.itemSkill(row, table: table, owner: owner))
        }
        return out.mapValues { $0.sorted() }
    }
}

extension PackItem {
    /// The fields of the item the engine reads.
    public var indexItem: ContentIndex.Item {
        ContentIndex.Item(
            id: id, kind: kind, it: it, gloss: glossEn, altGlosses: altGlossesEn, pos: pos, gender: gender,
            displayDef: displayDef, displayIndef: displayIndef, recallAnswer: recallAnswer, topics: topics,
            unitId: unitId, lessonId: lessonId, skills: skills)
    }
}
