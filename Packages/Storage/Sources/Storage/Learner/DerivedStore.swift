import Foundation
import GRDB
import LearningCore

/// How `LearnerState` is persisted (docs/03 § The learner database, "Derived state"):
///
/// - **The derived tables** (`memory`, `introductions`, `step_progress`, `unit_progress`, `can_do_status`,
///   `exercise_history`, `focus_items`, `daily_activity`) are a queryable projection of the state, rewritten row by
///   row in the transaction that appends the events: only the rows that differ between the state before and after.
/// - **The checkpoint** (`derived_checkpoint.state`) is the whole state as `LearnerState.canonicalEncoding()`,
///   including what the tables don't hold (the resume cursor's open start and answered exercises, unit start and
///   skip flags, last outcomes and contexts, format rotation, seconds-per-card samples, open review sessions,
///   catch-up counts, the final check and placement). It is written after every rebuild and then every
///   `checkpointInterval` events, not on every append, so a busy learner doesn't rewrite a large blob per answer.
/// - **`derived_meta`** records `derived_version`, `content_hash`, `last_applied_at`/`last_applied_id` and
///   `event_count` for the tables, all updated in the append transaction.
///
/// Opening loads the checkpoint and replays the events that sort after its `lastApplied` (at most
/// `checkpointInterval` of them). That is exact because every transaction that inserts events also applies them:
/// incrementally when they all sort after the last applied event, otherwise by a full rebuild, which writes a new
/// checkpoint. So the events missing from the checkpoint are exactly those after its `lastApplied`.
enum DerivedStore {
    // MARK: Rebuild and load

    /// Replays the whole log in `(at, id)` order straight from the table (without holding it in memory), then
    /// rewrites the derived tables, the checkpoint and `derived_meta`. A row that can't be read is skipped and
    /// logged (it still counts, so `event_count` matches the table).
    static func rebuild(_ db: Database, content: ContentIndex, logger: any CoreLogger) throws -> LearnerState {
        var state = Replay.initialState(content: content)
        var count = 0
        let rows = try Row.fetchCursor(db, sql: "SELECT \(EventRow.columns) FROM events ORDER BY at, id")
        while let row = try rows.next() {
            count += 1
            do {
                Replay.reduce(&state, try EventRow(row: row).event, content: content, logger: logger)
            } catch {
                logger.log("replay: skipped an unreadable events row: \(error)")
            }
        }
        try writeAllTables(db, state)
        try writeCheckpoint(db, state)
        try DerivedMeta(
            derivedVersion: Replay.derivedVersion, contentHash: content.contentHash,
            lastApplied: state.lastApplied, eventCount: count
        ).write(db)
        return state
    }

    /// The state saved by the last checkpoint, brought up to date with the events after it; nil when there is no
    /// usable checkpoint or it disagrees with `derived_meta` (then the caller rebuilds).
    static func load(
        _ db: Database, meta: DerivedMeta, content: ContentIndex, logger: any CoreLogger
    ) throws
        -> (state: LearnerState, caughtUp: Int)?
    {
        guard let data = try Data.fetchOne(db, sql: "SELECT state FROM derived_checkpoint WHERE id = 1") else {
            return nil
        }
        var state: LearnerState
        do {
            state = try JSONDecoder().decode(LearnerState.self, from: data)
        } catch {
            logger.log("replay: the derived-state checkpoint doesn't decode (\(error)); rebuilding")
            return nil
        }
        let later = try events(after: state.lastApplied, db, logger: logger)
        if !later.isEmpty, !Replay.applyIncremental(to: &state, events: later, content: content, logger: logger) {
            return nil
        }
        let count = try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM events") ?? 0
        guard state.lastApplied == meta.lastApplied, meta.eventCount == count else {
            logger.log("replay: the checkpoint and derived_meta disagree with the event log; rebuilding")
            return nil
        }
        return (state, later.count)
    }

    /// Events that sort after `key` in `(at, id)` order (all of them for nil). A row that can't be read is skipped
    /// and logged, as in `rebuild` (the schema's constraints make one all but impossible).
    static func events(after key: EventKey?, _ db: Database, logger: any CoreLogger) throws -> [Event] {
        let sql = "SELECT \(EventRow.columns) FROM events"
        let rows: [Row]
        if let key {
            rows = try Row.fetchAll(
                db, sql: sql + " WHERE at > ? OR (at = ? AND id > ?) ORDER BY at, id",
                arguments: [key.at, key.at, key.id])
        } else {
            rows = try Row.fetchAll(db, sql: sql + " ORDER BY at, id")
        }
        return rows.compactMap { row in
            do {
                return try EventRow(row: row).event
            } catch {
                logger.log("replay: skipped an unreadable events row: \(error)")
                return nil
            }
        }
    }

    // MARK: Checkpoint and meta

    static func writeCheckpoint(_ db: Database, _ state: LearnerState) throws {
        let data: Data
        do {
            data = try state.canonicalEncoding()
        } catch {
            throw StorageError.invalidValue(table: "derived_checkpoint", id: "1", reason: "\(error)")
        }
        try db.execute(sql: "INSERT OR REPLACE INTO derived_checkpoint (id, state) VALUES (1, ?)", arguments: [data])
    }

    // MARK: Tables

    /// Clears every derived table and writes the whole state.
    static func writeAllTables(_ db: Database, _ state: LearnerState) throws {
        for table in LearnerSchema.derivedTables { try db.execute(sql: "DELETE FROM \(table)") }
        try writeChanges(db, from: LearnerState(), to: state)
    }

    /// Writes the rows that differ between two states: upserts for new or changed keys, deletes for keys that went
    /// away. A collection the event didn't touch still shares its storage with the old state, so comparing it costs
    /// nothing.
    static func writeChanges(_ db: Database, from old: LearnerState, to new: LearnerState) throws {
        try sync(
            db, old.memory, new.memory,
            upsert: """
                INSERT OR REPLACE INTO memory (item_id, skill, stability, difficulty, last_review, due, reps, \
                lapses) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
            delete: "DELETE FROM memory WHERE item_id = ? AND skill = ?",
            key: { [$0.itemId.rawValue, $0.skill.rawValue] },
            values: { [$0.stability, $0.difficulty, $0.lastReviewMs, $0.dueMs, $0.reps, $0.lapses] })
        try sync(
            db, old.introductions, new.introductions,
            upsert: "INSERT OR REPLACE INTO introductions (item_id, skill, at, via) VALUES (?, ?, ?, ?)",
            delete: "DELETE FROM introductions WHERE item_id = ? AND skill = ?",
            key: { [$0.itemId.rawValue, $0.skill.rawValue] },
            values: { [$0.at, $0.via.rawValue] })
        try sync(
            db, old.steps, new.steps,
            upsert: """
                INSERT OR REPLACE INTO step_progress (step_id, started_at, completed_at, cursor) \
                VALUES (?, ?, ?, ?)
                """,
            delete: "DELETE FROM step_progress WHERE step_id = ?",
            key: { [$0.rawValue] },
            values: { [$0.startedAt, $0.completedAt, $0.cursor] })
        try sync(
            db, old.units, new.units,
            upsert: """
                INSERT OR REPLACE INTO unit_progress (unit_id, state, check_score, check_passed, completed_at) \
                VALUES (?, ?, ?, ?, ?)
                """,
            delete: "DELETE FROM unit_progress WHERE unit_id = ?",
            key: { [$0.rawValue] },
            values: { [$0.state.rawValue, $0.checkScore, $0.checkPassed, $0.completedAt] })
        try sync(
            db, old.canDos, new.canDos,
            upsert: "INSERT OR REPLACE INTO can_do_status (can_do_id, reached_at) VALUES (?, ?)",
            delete: "DELETE FROM can_do_status WHERE can_do_id = ?",
            key: { [$0.rawValue] },
            values: { [$0] })
        try sync(
            db, old.exerciseHistory, new.exerciseHistory,
            upsert: """
                INSERT OR REPLACE INTO exercise_history (exercise_id, last_at, attempts, first_try_correct) \
                VALUES (?, ?, ?, ?)
                """,
            delete: "DELETE FROM exercise_history WHERE exercise_id = ?",
            key: { [$0.rawValue] },
            values: { [$0.lastAt, $0.attempts, $0.firstTryCorrect] })
        try sync(
            db, old.focusItems, new.focusItems,
            upsert: "INSERT OR REPLACE INTO focus_items (item_id, skill, reason, until) VALUES (?, ?, ?, ?)",
            delete: "DELETE FROM focus_items WHERE item_id = ? AND skill = ?",
            key: { [$0.itemId.rawValue, $0.skill.rawValue] },
            values: { [$0.reason, $0.until] })
        try sync(
            db, old.dailyActivity, new.dailyActivity,
            upsert: """
                INSERT OR REPLACE INTO daily_activity (local_day, active_seconds, steps_completed, \
                cards_reviewed) VALUES (?, ?, ?, ?)
                """,
            delete: "DELETE FROM daily_activity WHERE local_day = ?",
            key: { [LocalDay.string(dayNumber: $0)] },
            values: { [$0.activeSeconds, $0.stepsCompleted, $0.cardsReviewed] })
    }

    /// Upserts the entries of `new` that differ from `old` and deletes the keys `new` no longer has.
    private static func sync<K: Hashable, V: Equatable>(
        _ db: Database, _ old: [K: V], _ new: [K: V], upsert: String, delete: String,
        key: (K) -> [(any DatabaseValueConvertible)?], values: (V) -> [(any DatabaseValueConvertible)?]
    ) throws {
        guard old != new else { return }
        let upsertStatement = try db.cachedStatement(sql: upsert)
        for (k, v) in new where old[k] != v {
            try upsertStatement.execute(arguments: StatementArguments(key(k) + values(v)))
        }
        guard old.count > 0 else { return }
        let deleteStatement = try db.cachedStatement(sql: delete)
        for k in old.keys where new[k] == nil {
            try deleteStatement.execute(arguments: StatementArguments(key(k)))
        }
    }
}

/// `derived_meta` (docs/03): what the derived tables were computed with and up to which event.
struct DerivedMeta: Equatable {
    var derivedVersion: Int?
    var contentHash: String?
    var lastApplied: EventKey?
    var eventCount: Int?

    static func read(_ db: Database) throws -> DerivedMeta {
        var values: [String: String] = [:]
        for row in try Row.fetchAll(db, sql: "SELECT key, value FROM derived_meta") {
            if let key: String = try? row.decode(String.self, atIndex: 0),
                let value: String = try? row.decode(String.self, atIndex: 1)
            {
                values[key] = value
            }
        }
        var lastApplied: EventKey?
        if let at = values["last_applied_at"].flatMap({ Int64($0) }), let id = values["last_applied_id"] {
            lastApplied = EventKey(at: at, id: id)
        }
        return DerivedMeta(
            derivedVersion: values["derived_version"].flatMap { Int($0) },
            contentHash: values["content_hash"], lastApplied: lastApplied,
            eventCount: values["event_count"].flatMap { Int($0) })
    }

    func write(_ db: Database) throws {
        let pairs: [(String, String?)] = [
            ("derived_version", derivedVersion.map(String.init)), ("content_hash", contentHash),
            ("last_applied_at", lastApplied.map { String($0.at) }), ("last_applied_id", lastApplied?.id),
            ("event_count", eventCount.map(String.init)),
        ]
        let upsert = try db.cachedStatement(sql: "INSERT OR REPLACE INTO derived_meta (key, value) VALUES (?, ?)")
        let delete = try db.cachedStatement(sql: "DELETE FROM derived_meta WHERE key = ?")
        for (key, value) in pairs {
            if let value { try upsert.execute(arguments: [key, value]) } else { try delete.execute(arguments: [key]) }
        }
    }
}
