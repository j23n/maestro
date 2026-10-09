import Foundation
import GRDB
import LearningCore

/// What `PackReader.verify()` found: how many rows of each table decoded, and every problem.
public struct PackVerification: Sendable, Equatable {
    /// Rows that decoded, per table.
    public let decoded: [String: Int]
    /// Rows that don't decode or contradict their columns, and references from a payload to a missing row.
    public let problems: [PackError]

    public var isClean: Bool { problems.isEmpty }
}

extension PackReader {
    /// Decodes every JSON column of the pack through the same code the queries use (steps, exercises, notes,
    /// assessments, texts with their lines, tokens and layouts, items, letter names, sounds, countries) and checks
    /// that every ID a payload names exists (a step's exercises, texts and note; an exercise's texts; an assessment's
    /// exercises; a note's example texts). The pack tests run it over `fixtures/packs/mini.sqlite`; it reads the
    /// whole pack.
    public func verify() async throws(PackError) -> PackVerification {
        try await read { db in try Self.verify(db) }
    }

    static func verify(_ db: Database) throws -> PackVerification {
        var decoded: [String: Int] = [:]
        var problems: [PackError] = []
        func attempt(_ table: String, _ body: () throws -> Void) {
            do {
                try body()
                decoded[table, default: 0] += 1
            } catch {
                problems.append(PackError.wrap(error))
            }
        }
        let exerciseIDs = Set(try String.fetchAll(db, sql: "SELECT id FROM exercises"))
        let textIDs = Set(try String.fetchAll(db, sql: "SELECT id FROM texts"))
        let noteIDs = Set(try String.fetchAll(db, sql: "SELECT id FROM grammar_notes"))
        func dangling(_ table: String, _ owner: String, _ kind: String, _ ids: [String], in known: Set<String>) {
            for id in ids where !known.contains(id) {
                problems.append(.malformedRow(table: table, id: owner, reason: "names a missing \(kind) \(id)"))
            }
        }

        for row in try db.packRows(PackSQL.steps) {
            attempt("steps") {
                let step = try PackRows.step(row)
                let check = indexStep(step, introduces: []).0
                dangling("steps", step.id.rawValue, "exercise", check.exerciseIds.map(\.rawValue), in: exerciseIDs)
                dangling("steps", step.id.rawValue, "text", step.textIds.map(\.rawValue), in: textIDs)
                dangling("steps", step.id.rawValue, "note", check.noteId.map { [$0.rawValue] } ?? [], in: noteIDs)
            }
        }
        let targets = try pairs(db, PackSQL.exerciseTargets, table: "exercise_targets", owner: "exercise_id")
        for row in try db.packRows(PackSQL.allExercisePayloads) {
            attempt("exercises") {
                let exercise = try PackRows.exercise(row)
                let id = exercise.id.rawValue
                let named = exercise.payload.targets.map { ItemSkillPair($0.itemId, $0.skill) }.sorted()
                if named != (targets[id] ?? []) {
                    throw PackError.malformedRow(table: "exercises", id: id,
                                                 reason: "payload targets differ from exercise_targets")
                }
                dangling("exercises", id, "text", textReferences(exercise.payload).map(\.rawValue), in: textIDs)
            }
        }
        for row in try db.packRows(PackSQL.allNotes) {
            attempt("grammar_notes") {
                let id = try PackRow(row, table: "grammar_notes").string("id")
                let grammar = try db.packRows(PackSQL.noteItems, [id]).map { r in
                    ItemID(try PackRow(r, table: "note_items", id: id).string("item_id"))
                }
                let note = try PackRows.note(row, grammar: grammar)
                if note.body.grammar != grammar {
                    throw PackError.malformedRow(table: "grammar_notes", id: id,
                                                 reason: "body.grammar differs from note_items")
                }
                let examples = note.body.blocks.flatMap { block -> [String] in
                    if case .examples(let e) = block { return e.map(\.textId.rawValue) }
                    return []
                }
                dangling("grammar_notes", id, "text", examples, in: textIDs)
            }
        }
        for row in try db.packRows(PackSQL.assessments) {
            attempt("assessments") {
                let id = try PackRow(row, table: "assessments").string("id")
                let named: [ExerciseID] =
                    switch try PackRows.assessment(row) {
                    case .placement(_, let blocks): blocks.flatMap(\.exerciseIds)
                    case .final(_, let sections): sections.flatMap(\.exerciseIds)
                    }
                dangling("assessments", id, "exercise", named.map(\.rawValue), in: exerciseIDs)
            }
        }
        for id in textIDs.sorted() {
            attempt("texts") { _ = try text(db, TextID(id)) }
        }
        do {
            decoded["items"] = try allItems(db).count
        } catch {
            problems.append(PackError.wrap(error))
        }
        do {
            decoded["letters"] = try letterNames(db).count
        } catch {
            problems.append(PackError.wrap(error))
        }
        for row in try db.packRows(PackSQL.sounds) {
            attempt("sounds") { _ = try PackRows.sounds(row) }
        }
        for row in try db.packRows(PackSQL.countries) {
            attempt("countries") { _ = try PackRows.country(row) }
        }
        return PackVerification(decoded: decoded, problems: problems)
    }

    /// The texts an exercise payload names.
    static func textReferences(_ payload: ExercisePayload) -> [TextID] {
        var ids = payload.source.map { [$0.textId] } ?? []
        switch payload.body {
        case .choice(let c): ids += c.audioTextId.map { [$0] } ?? []
        case .trueFalse(let t): ids += t.audioTextId.map { [$0] } ?? []
        case .relay(let r): ids += [r.sourceTextId, r.audioTextId].compactMap { $0 }
        default: break
        }
        return ids
    }
}
