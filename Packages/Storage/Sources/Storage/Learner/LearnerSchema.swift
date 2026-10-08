import Foundation
import GRDB

/// The learner database's GRDB migrations (docs/03 § The learner database). Never edit a migration once it has
/// shipped: add `v2`, `v3`… (docs/02 § Storage). Derived tables hold nothing that replay can't rebuild, so a later
/// migration may drop and recreate them and bump `Replay.derivedVersion`.
enum LearnerSchema {
    static func migrator() -> DatabaseMigrator {
        var migrator = DatabaseMigrator()
        migrator.registerMigration("v1") { db in try db.execute(sql: v1) }
        return migrator
    }

    /// Every table of docs/03's reference DDL, plus `derived_checkpoint` (the whole `LearnerState`) and
    /// `local_meta` (this install's device ID).
    static let v1 = """
        -- the source of truth: immutable, append-only, synced
        CREATE TABLE events (
          id            TEXT PRIMARY KEY,
          at            INTEGER NOT NULL,
          tz_offset_min INTEGER NOT NULL,
          type          TEXT NOT NULL,
          device_id     TEXT NOT NULL,
          schema        INTEGER NOT NULL,
          pack_version  TEXT NOT NULL,
          payload       TEXT NOT NULL,
          origin        TEXT NOT NULL CHECK (origin IN ('local','remote'))
        );
        CREATE INDEX events_order ON events(at, id);

        -- derived: rebuildable at any time from events + pack
        CREATE TABLE memory (item_id TEXT, skill TEXT, stability REAL NOT NULL, difficulty REAL NOT NULL,
          last_review INTEGER NOT NULL, due INTEGER NOT NULL, reps INTEGER NOT NULL, lapses INTEGER NOT NULL,
          PRIMARY KEY (item_id, skill));
        CREATE TABLE introductions (item_id TEXT, skill TEXT, at INTEGER NOT NULL, via TEXT NOT NULL,
          PRIMARY KEY (item_id, skill));
        CREATE TABLE step_progress (step_id TEXT PRIMARY KEY, started_at INTEGER, completed_at INTEGER,
          cursor INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE unit_progress (unit_id TEXT PRIMARY KEY, state TEXT NOT NULL,
          check_score REAL, check_passed INTEGER, completed_at INTEGER);
        CREATE TABLE can_do_status (can_do_id TEXT PRIMARY KEY, reached_at INTEGER NOT NULL);
        CREATE TABLE exercise_history (exercise_id TEXT PRIMARY KEY, last_at INTEGER NOT NULL,
          attempts INTEGER NOT NULL, first_try_correct INTEGER NOT NULL);
        CREATE TABLE focus_items (item_id TEXT, skill TEXT, reason TEXT NOT NULL, until INTEGER NOT NULL,
          PRIMARY KEY (item_id, skill));
        CREATE TABLE daily_activity (local_day TEXT PRIMARY KEY, active_seconds INTEGER NOT NULL,
          steps_completed INTEGER NOT NULL, cards_reviewed INTEGER NOT NULL);
        CREATE TABLE derived_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE derived_checkpoint (id INTEGER PRIMARY KEY CHECK (id = 1), state BLOB NOT NULL);

        -- settings: per-key last-writer-wins
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL,
          device_id TEXT NOT NULL, scope TEXT NOT NULL CHECK (scope IN ('synced','device')));

        -- sync bookkeeping (docs/08)
        CREATE TABLE sync_engine_state (id INTEGER PRIMARY KEY CHECK (id = 1), data BLOB);
        CREATE TABLE cloud_system_fields (record_name TEXT PRIMARY KEY, data BLOB NOT NULL);
        CREATE TABLE sync_pending (record_name TEXT PRIMARY KEY, kind TEXT NOT NULL, added_at INTEGER NOT NULL);

        -- study telemetry bookkeeping (docs/12): device-local, never synced, never rebuilt
        CREATE TABLE telemetry_sent (event_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, sent_at INTEGER NOT NULL);

        -- this install: device-local, never synced, never rebuilt
        CREATE TABLE local_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """

    /// The derived tables replay writes (docs/03), in the order a full rewrite clears them.
    static let derivedTables = [
        "memory", "introductions", "step_progress", "unit_progress", "can_do_status", "exercise_history",
        "focus_items", "daily_activity",
    ]

    /// Every table of `v1`, for the migration test.
    static let allTables =
        ["events"] + derivedTables + [
            "derived_meta", "derived_checkpoint", "settings", "sync_engine_state", "cloud_system_fields",
            "sync_pending", "telemetry_sent", "local_meta",
        ]
}
