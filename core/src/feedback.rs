//! The pending-feedback queue (plan §2.1's LLM-layer contract).
//!
//! Lifecycle: the shell enqueues a job when the learner submits writing
//! (or wants an explanation) — online or not. When a backend is
//! available AND eval-gated on, the shell lists pending jobs, calls the
//! backend, and completes each job with a `FeedbackResult`; completion
//! stores the result and folds any evidence event straight back into
//! the learner record, stamped with the backend that produced it.
//!
//! Jobs live in the learner DB (`feedback_jobs`), so queued submissions
//! survive restarts and export/backup concerns stay in one file.

use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::{Connection, OptionalExtension};

use crate::model::{FeedbackJobRequest, FeedbackResult};
use crate::CoreError;

fn now_secs() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock before 1970")
        .as_secs() as i64
}

pub fn enqueue(conn: &Connection, request_json: &str) -> Result<i64, CoreError> {
    let request: FeedbackJobRequest =
        serde_json::from_str(request_json).map_err(|e| CoreError::Invalid {
            message: format!("feedback request does not match schema: {e}"),
        })?;
    request
        .validate()
        .map_err(|message| CoreError::Invalid { message })?;
    conn.execute(
        "INSERT INTO feedback_jobs (created_at, request) VALUES (?1, ?2)",
        rusqlite::params![now_secs(), request_json],
    )?;
    Ok(conn.last_insert_rowid())
}

/// Pending jobs, oldest first, as JSON objects:
/// `{"id": …, "created_at": …, "request": {…}}`.
pub fn list_pending(conn: &Connection) -> Result<Vec<String>, CoreError> {
    let mut stmt = conn.prepare(
        "SELECT id, created_at, request FROM feedback_jobs
         WHERE status = 'pending' ORDER BY id",
    )?;
    let rows = stmt
        .query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, String>(2)?,
            ))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    rows.into_iter()
        .map(|(id, created_at, request)| {
            let request: serde_json::Value =
                serde_json::from_str(&request).map_err(|e| CoreError::Storage {
                    message: format!("corrupt feedback job {id}: {e}"),
                })?;
            Ok(serde_json::json!({
                "id": id, "created_at": created_at, "request": request
            })
            .to_string())
        })
        .collect()
}

/// Store a backend's result and fold its evidence (if any) back into
/// the learner record. `backend` is stamped as the event's
/// `feedback_source` — the UI's "who said this" label reads it.
pub fn complete(
    conn: &Connection,
    job_id: i64,
    backend: &str,
    result_json: &str,
) -> Result<(), CoreError> {
    let status: Option<String> = conn
        .query_row(
            "SELECT status FROM feedback_jobs WHERE id = ?1",
            [job_id],
            |r| r.get(0),
        )
        .optional()?;
    match status.as_deref() {
        None => {
            return Err(CoreError::NotFound {
                message: format!("feedback job {job_id}"),
            })
        }
        Some("pending") => {}
        Some(other) => {
            return Err(CoreError::Invalid {
                message: format!("feedback job {job_id} is already {other}"),
            })
        }
    }

    let mut result: FeedbackResult =
        serde_json::from_str(result_json).map_err(|e| CoreError::Invalid {
            message: format!("feedback result does not match schema: {e}"),
        })?;

    if let Some(ev) = result.evidence_event.as_mut() {
        if ev.feedback_source.is_none() {
            ev.feedback_source = Some(backend.to_string());
        }
        ev.validate().map_err(|message| CoreError::Invalid {
            message: format!("feedback evidence event: {message}"),
        })?;
        let payload = serde_json::to_string(ev).map_err(|e| CoreError::Storage {
            message: e.to_string(),
        })?;
        crate::events::record(conn, &payload)?;
    }

    conn.execute(
        "UPDATE feedback_jobs
         SET status = 'completed', completed_at = ?2, backend = ?3, result = ?4
         WHERE id = ?1",
        rusqlite::params![job_id, now_secs(), backend, result_json],
    )?;
    Ok(())
}
