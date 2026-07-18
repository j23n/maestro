//! Maestro portable core — everything platform-neutral, behind a
//! UniFFI-exported API a SwiftUI (later Kotlin) shell calls.
//!
//! In here: the pack reader (bundle open + schema compat, items, media,
//! tombstones, embedded spec), deterministic scoring + the transcript
//! alignment scorer, the append-only learner record with export/import
//! backup, derived-state folds (decayed mastery, SM-2 vocab scheduling
//! — FSRS deliberately deferred, decisions.md #5 — functions, scenario
//! depth, can-do rollup), the session composer, and the LLM
//! pending-feedback queue. Conformance vectors in ../conformance/ pin
//! folds, composer, scoring, normalization, and alignment for any
//! future second implementation.
//!
//! Boundary rule (docs/plans/03-implementation-plan.md §2.1): if it
//! would behave identically on Android it lives here; anything touching
//! a platform API (UI, speech, network) is the shell's job.

pub mod align;
mod events;
pub mod feedback;
pub mod folds;
pub mod model;
pub mod normalize;
pub mod pack;
pub mod session;

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

/// Pack identity + compatibility + contents, for the pack-manager UI.
#[derive(Debug, Clone, uniffi::Record)]
pub struct PackStatus {
    /// False when the bundle's schema_version is newer than this core
    /// supports — the shell should prompt for an app update, not read on.
    pub compatible: bool,
    pub schema_version: String,
    pub pack_version: String,
    pub language: String,
    pub item_count: u32,
    pub media_count: u32,
    pub tombstone_count: u32,
}

/// A media asset's inventory row (bytes fetched separately).
#[derive(Debug, Clone, uniffi::Record)]
pub struct MediaInfo {
    pub path: String,
    pub kind: String, // audio | image
    pub sha256: String,
    pub size_bytes: u64,
}

/// A media asset with its bytes.
#[derive(Debug, Clone, uniffi::Record)]
pub struct MediaBlob {
    pub kind: String,
    pub sha256: String,
    pub bytes: Vec<u8>,
}

/// A removed item's forwarding record.
#[derive(Debug, Clone, uniffi::Record)]
pub struct TombstoneRecord {
    pub item_id: String,
    pub removed_in: String,
    pub reason: Option<String>,
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

    /// Identity, compatibility, and contents of the open pack — what the
    /// pack-manager screen shows, and what update flows check.
    pub fn pack_status(&self) -> Result<PackStatus, CoreError> {
        pack::pack_status(&self.pack.lock().unwrap())
    }

    /// Media inventory (paths as referenced by item payloads).
    pub fn list_media(&self) -> Result<Vec<MediaInfo>, CoreError> {
        pack::list_media(&self.pack.lock().unwrap())
    }

    /// One media asset with its bytes (audio to play, image to render).
    pub fn get_media(&self, path: String) -> Result<MediaBlob, CoreError> {
        pack::get_media(&self.pack.lock().unwrap(), &path)
    }

    /// Removed-item records; learner history referencing these ids stays
    /// interpretable after a pack update.
    pub fn list_tombstones(&self) -> Result<Vec<TombstoneRecord>, CoreError> {
        pack::list_tombstones(&self.pack.lock().unwrap())
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

    /// The whole learner record as portable JSONL (backup). The shell
    /// decides where the bytes go; restore with `import_log`.
    pub fn export_log(&self) -> Result<String, CoreError> {
        events::export_log(&self.learner.lock().unwrap())
    }

    /// Restore an exported log into this (empty) learner record.
    /// All-or-nothing; returns the number of events restored.
    pub fn import_log(&self, data: String) -> Result<u32, CoreError> {
        events::import_log(&self.learner.lock().unwrap(), &data)
    }

    /// Queue a feedback job (`model::FeedbackJobRequest` JSON) for the
    /// next available LLM backend. Works offline; returns the job id.
    pub fn enqueue_feedback_job(&self, request_json: String) -> Result<i64, CoreError> {
        feedback::enqueue(&self.learner.lock().unwrap(), &request_json)
    }

    /// Pending feedback jobs, oldest first
    /// (`{"id", "created_at", "request"}` JSON objects).
    pub fn list_pending_feedback_jobs(&self) -> Result<Vec<String>, CoreError> {
        feedback::list_pending(&self.learner.lock().unwrap())
    }

    /// Complete a job with a backend's `model::FeedbackResult` JSON:
    /// stores the result and folds its evidence event (if any) back
    /// into the learner record, stamped with `backend` as the
    /// feedback source.
    pub fn complete_feedback_job(
        &self,
        job_id: i64,
        backend: String,
        result_json: String,
    ) -> Result<(), CoreError> {
        feedback::complete(&self.learner.lock().unwrap(), job_id, &backend, &result_json)
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

    /// Compose the next session (`model::SessionPlan`) as JSON.
    /// Options JSON matches `model::SessionOptions` ({now, time_budget_minutes,
    /// scenario_id?, seed}).
    pub fn compose_session(&self, options_json: String) -> Result<String, CoreError> {
        let opts: model::SessionOptions =
            serde_json::from_str(&options_json).map_err(|e| CoreError::Invalid {
                message: format!("bad session options: {e}"),
            })?;
        let events = self.load_events()?;
        let pack_conn = self.pack.lock().unwrap();
        let spec = pack::load_spec(&pack_conn)?;
        let items = pack::list_item_meta(&pack_conn)?;
        drop(pack_conn);
        let state = folds::fold(&events, &spec, opts.now);
        let plan = session::compose(&items, &spec, &state, &opts);
        serde_json::to_string(&plan).map_err(|e| CoreError::Storage {
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
