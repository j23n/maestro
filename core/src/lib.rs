//! Maestro portable core — Phase 0 walking skeleton.
//!
//! Scope (docs/plans/03-implementation-plan.md §5, Phase 0): prove the
//! core boundary end-to-end — open a pack SQLite bundle, fetch an item,
//! score an answer deterministically, append an evidence event, read it
//! back — behind a UniFFI-exported API a SwiftUI shell can call.
//!
//! The typed learner model and derived-state folds live in `model` and
//! `folds`; session composition arrives in the next stage.

mod events;
pub mod folds;
pub mod model;
mod normalize;
pub mod pack;

use std::sync::{Arc, Mutex};

use rusqlite::Connection;

uniffi::setup_scaffolding!();

#[derive(Debug, thiserror::Error, uniffi::Error)]
pub enum CoreError {
    #[error("storage error: {message}")]
    Storage { message: String },
    #[error("not found: {message}")]
    NotFound { message: String },
    #[error("invalid input: {message}")]
    Invalid { message: String },
}

impl From<rusqlite::Error> for CoreError {
    fn from(e: rusqlite::Error) -> Self {
        match e {
            rusqlite::Error::QueryReturnedNoRows => CoreError::NotFound {
                message: "no such row".into(),
            },
            other => CoreError::Storage {
                message: other.to_string(),
            },
        }
    }
}

/// Pack metadata, read from the bundle's `manifest` table.
#[derive(Debug, Clone, uniffi::Record)]
pub struct PackManifest {
    pub schema_version: String,
    pub pack_version: String,
    pub language: String,
    pub item_count: u32,
}

/// Result of deterministically scoring a closed-form attempt.
#[derive(Debug, Clone, uniffi::Record)]
pub struct ScoreResult {
    pub correct: bool,
    /// The acceptable answer the (normalized) response matched, if any.
    pub matched_answer: Option<String>,
    /// The canonical answer(s), for display on a miss.
    pub expected: Vec<String>,
    /// Pre-authored feedback: distractor-specific if the wrong answer was
    /// anticipated, otherwise the item's general explanation, if present.
    pub feedback: Option<String>,
}

/// The core's entry point. One instance per (pack, learner) pair.
///
/// The API is deliberately coarse-grained: values cross the FFI as records
/// or JSON strings, and each call is a complete operation.
#[derive(uniffi::Object)]
pub struct Core {
    pack: Mutex<Connection>,
    learner: Mutex<Connection>,
}

#[uniffi::export]
impl Core {
    /// Open a read-only content pack and a read-write learner database.
    /// The learner database is created and migrated if missing.
    #[uniffi::constructor]
    pub fn open(pack_path: String, learner_db_path: String) -> Result<Arc<Self>, CoreError> {
        let pack = pack::open_readonly(&pack_path)?;
        let learner = events::open_learner_db(&learner_db_path)?;
        Ok(Arc::new(Core {
            pack: Mutex::new(pack),
            learner: Mutex::new(learner),
        }))
    }

    pub fn manifest(&self) -> Result<PackManifest, CoreError> {
        pack::read_manifest(&self.pack.lock().unwrap())
    }

    pub fn list_item_ids(&self) -> Result<Vec<String>, CoreError> {
        pack::list_item_ids(&self.pack.lock().unwrap())
    }

    /// The item's typed payload, as JSON (shape depends on `item_type`).
    pub fn get_item_json(&self, item_id: String) -> Result<String, CoreError> {
        pack::get_item_json(&self.pack.lock().unwrap(), &item_id)
    }

    /// Deterministic scoring: normalize, match against the item's
    /// acceptable answers, and look up pre-authored feedback on a miss.
    pub fn score_attempt(
        &self,
        item_id: String,
        response: String,
    ) -> Result<ScoreResult, CoreError> {
        pack::score_attempt(&self.pack.lock().unwrap(), &item_id, &response)
    }

    /// Append an evidence event (a JSON object matching `model::EvidenceEvent`)
    /// to the learner record. Validated before insert.
    pub fn record_event(&self, event_json: String) -> Result<(), CoreError> {
        let ev: model::EvidenceEvent =
            serde_json::from_str(&event_json).map_err(|e| CoreError::Invalid {
                message: format!("event does not match schema: {e}"),
            })?;
        ev.validate().map_err(|message| CoreError::Invalid { message })?;
        events::record(&self.learner.lock().unwrap(), &event_json)
    }

    /// All recorded events, oldest first, as JSON objects.
    pub fn list_events_json(&self) -> Result<Vec<String>, CoreError> {
        events::list(&self.learner.lock().unwrap())
    }

    /// Full derived learner state (`model::DerivedState`) as JSON.
    /// `now` is unix seconds — explicit so folds are deterministic.
    pub fn progress_summary(&self, now: i64) -> Result<String, CoreError> {
        let events = self.load_events()?;
        let spec = pack::load_spec(&self.pack.lock().unwrap())?;
        let state = folds::fold(&events, &spec, now);
        serde_json::to_string(&state).map_err(|e| CoreError::Storage {
            message: e.to_string(),
        })
    }
}

impl Core {
    fn load_events(&self) -> Result<Vec<model::EvidenceEvent>, CoreError> {
        let raw = events::list_with_times(&self.learner.lock().unwrap())?;
        let mut out = Vec::with_capacity(raw.len());
        for (created_at, payload) in raw {
            let mut ev: model::EvidenceEvent =
                serde_json::from_str(&payload).map_err(|e| CoreError::Storage {
                    message: format!("corrupt event in log: {e}"),
                })?;
            if ev.at.is_none() {
                ev.at = Some(created_at);
            }
            out.push(ev);
        }
        Ok(out)
    }
}
