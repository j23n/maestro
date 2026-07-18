//! Maestro portable core — Phase 0 walking skeleton.
//!
//! Scope (docs/plans/03-implementation-plan.md §5, Phase 0): prove the
//! core boundary end-to-end — open a pack SQLite bundle, fetch an item,
//! score an answer deterministically, append an evidence event, read it
//! back — behind a UniFFI-exported API a SwiftUI shell can call.
//!
//! The full folds (mastery, SRS, session composition) arrive in later
//! stages; nothing here should need rework for them, only extension.

mod events;
pub mod normalize;
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

    /// Append an evidence event (a JSON object) to the learner record.
    /// Schema validation arrives with the typed learner model.
    pub fn record_event(&self, event_json: String) -> Result<(), CoreError> {
        events::record(&self.learner.lock().unwrap(), &event_json)
    }

    /// All recorded events, oldest first, as JSON objects.
    pub fn list_events_json(&self) -> Result<Vec<String>, CoreError> {
        events::list(&self.learner.lock().unwrap())
    }
}
