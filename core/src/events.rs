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
         );
         CREATE TABLE IF NOT EXISTS feedback_jobs (
             id           INTEGER PRIMARY KEY AUTOINCREMENT,
             created_at   INTEGER NOT NULL,
             request      TEXT NOT NULL,    -- model::FeedbackJobRequest JSON
             status       TEXT NOT NULL DEFAULT 'pending',
             completed_at INTEGER,
             backend      TEXT,             -- who answered (anthropic|apple_fm|...)
             result       TEXT              -- model::FeedbackResult JSON
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

/// (created_at, payload) pairs, oldest first — created_at backfills events
/// whose JSON carries no explicit `at`.
pub fn list_with_times(conn: &Connection) -> Result<Vec<(i64, String)>, CoreError> {
    let mut stmt = conn.prepare("SELECT created_at, payload FROM events ORDER BY seq")?;
    let events = stmt
        .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?
        .collect::<Result<Vec<(i64, String)>, _>>()?;
    Ok(events)
}

// --------------------------------------------------------------------------
// Backup: the whole learner record as a portable byte stream.

const EXPORT_HEADER: &str = r#"{"maestro_export":1}"#;

/// Serialize the full event log as JSONL: a version header line, then
/// one `{"created_at":…,"payload":{…}}` line per event, oldest first.
/// The core produces the bytes; where they go (Files, iCloud, AirDrop)
/// is the shell's business.
pub fn export_log(conn: &Connection) -> Result<String, CoreError> {
    let mut out = String::from(EXPORT_HEADER);
    out.push('\n');
    for (created_at, payload) in list_with_times(conn)? {
        let payload: serde_json::Value =
            serde_json::from_str(&payload).map_err(|e| CoreError::Storage {
                message: format!("corrupt event in log: {e}"),
            })?;
        let line = serde_json::json!({ "created_at": created_at, "payload": payload });
        out.push_str(&line.to_string());
        out.push('\n');
    }
    Ok(out)
}

/// Restore an exported log into an EMPTY learner database (refuses to
/// merge into existing history — restore is a fresh-device operation).
/// Every event is schema-validated before anything is written; returns
/// the number of events imported.
pub fn import_log(conn: &Connection, data: &str) -> Result<u32, CoreError> {
    let existing: u32 = conn.query_row("SELECT count(*) FROM events", [], |r| r.get(0))?;
    if existing > 0 {
        return Err(CoreError::Invalid {
            message: format!(
                "learner record already has {existing} events — import only \
                 restores into an empty record"
            ),
        });
    }
    let mut lines = data.lines().filter(|l| !l.trim().is_empty());
    let header: serde_json::Value = lines
        .next()
        .and_then(|l| serde_json::from_str(l).ok())
        .ok_or_else(|| CoreError::Invalid {
            message: "not a maestro export (missing header)".into(),
        })?;
    if header.get("maestro_export").and_then(|v| v.as_i64()) != Some(1) {
        return Err(CoreError::Invalid {
            message: "not a maestro export (bad header)".into(),
        });
    }

    // Validate everything first: an import either fully applies or not at all.
    let mut rows: Vec<(i64, String)> = Vec::new();
    for (n, line) in lines.enumerate() {
        let parsed: serde_json::Value =
            serde_json::from_str(line).map_err(|e| CoreError::Invalid {
                message: format!("line {}: not JSON: {e}", n + 2),
            })?;
        let created_at = parsed
            .get("created_at")
            .and_then(|v| v.as_i64())
            .ok_or_else(|| CoreError::Invalid {
                message: format!("line {}: missing created_at", n + 2),
            })?;
        let payload = parsed.get("payload").ok_or_else(|| CoreError::Invalid {
            message: format!("line {}: missing payload", n + 2),
        })?;
        let ev: crate::model::EvidenceEvent = serde_json::from_value(payload.clone())
            .map_err(|e| CoreError::Invalid {
                message: format!("line {}: event does not match schema: {e}", n + 2),
            })?;
        ev.validate().map_err(|message| CoreError::Invalid {
            message: format!("line {}: {message}", n + 2),
        })?;
        rows.push((created_at, payload.to_string()));
    }
    for (created_at, payload) in &rows {
        conn.execute(
            "INSERT INTO events (created_at, payload) VALUES (?1, ?2)",
            rusqlite::params![created_at, payload],
        )?;
    }
    Ok(rows.len() as u32)
}
