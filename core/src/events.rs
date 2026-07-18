//! The learner record: an append-only log of evidence events.
//!
//! Events are stored as the JSON the caller supplies (shape defined in
//! docs/plans/03-implementation-plan.md §4), plus a server-free insertion
//! timestamp. All derived learner state (Phase 3) is a fold over this
//! table; nothing here is ever updated or deleted.

use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::Connection;

use crate::CoreError;

pub fn open_learner_db(path: &str) -> Result<Connection, CoreError> {
    let conn = Connection::open(path)?;
    conn.execute_batch(
        "PRAGMA journal_mode = WAL;
         CREATE TABLE IF NOT EXISTS events (
             seq        INTEGER PRIMARY KEY AUTOINCREMENT,
             created_at INTEGER NOT NULL,   -- unix epoch seconds
             payload    TEXT NOT NULL       -- JSON object
         );",
    )?;
    Ok(conn)
}

pub fn record(conn: &Connection, event_json: &str) -> Result<(), CoreError> {
    let parsed: serde_json::Value =
        serde_json::from_str(event_json).map_err(|e| CoreError::Invalid {
            message: format!("event is not valid JSON: {e}"),
        })?;
    if !parsed.is_object() {
        return Err(CoreError::Invalid {
            message: "event must be a JSON object".into(),
        });
    }
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock before 1970")
        .as_secs();
    conn.execute(
        "INSERT INTO events (created_at, payload) VALUES (?1, ?2)",
        rusqlite::params![now, event_json],
    )?;
    Ok(())
}

pub fn list(conn: &Connection) -> Result<Vec<String>, CoreError> {
    let mut stmt = conn.prepare("SELECT payload FROM events ORDER BY seq")?;
    let events = stmt
        .query_map([], |row| row.get(0))?
        .collect::<Result<Vec<String>, _>>()?;
    Ok(events)
}
