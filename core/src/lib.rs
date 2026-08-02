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

use std::collections::{HashMap, HashSet};
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

/// One row of `vocab_inventory`. Crosses as JSON rather than as a UniFFI
/// record: it is a derived view assembled per call, not part of the
/// object graph, and the JSON convention already covers derived state.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct VocabEntry {
    pub lemma: String,
    pub cefr_level: String,
    pub pos: String,
    pub gloss: String,
    /// Present only for lemmas the pack authored a card for — the rest
    /// are inventory the learner can read but not yet practise.
    pub item_id: Option<String>,
    pub front: Option<String>,
    pub back: Option<String>,
    pub example: Option<String>,
    pub example_gloss: Option<String>,
    /// SM-2's streak, reset to zero by a lapse. `reviews` is the honest
    /// count of times the learner has practised the word.
    pub repetitions: u32,
    pub reviews: u32,
    pub interval_days: u32,
    pub ease_factor: f64,
    /// Negative when overdue; absent for a word never met.
    pub due_in_days: Option<i64>,
    /// Days since the word first appeared in a lesson; absent if it hasn't.
    pub first_seen_days_ago: Option<i64>,
    /// new | discovered | due | learning | known
    pub status: String,
}

/// A spec id resolved to the name a learner should see. Plans and events
/// carry ids only, and an id is never the right thing to put on screen.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct SpecLabel {
    pub id: String,
    pub label: String,
}

/// The authored framing of one lesson, with the learner's history at it.
/// Answers both "what am I about to do and why" before a session and
/// "what did I just cover" after one, so both screens read from one shape.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct LessonBrief {
    pub scenario_id: String,
    pub cefr_level: String,
    /// Falls back to the id on bundles built before the framing columns.
    pub label: String,
    pub description: String,
    pub overview: String,
    pub scene_setting: String,
    pub outro: String,
    /// Media path for `get_media`; empty when the lesson is unillustrated.
    pub image: String,
    pub grammar: Vec<SpecLabel>,
    pub functions: Vec<SpecLabel>,
    /// Depths finished here, out of `depth_count` — 0 means never played.
    pub completed_depths: u8,
    pub depth_count: u8,
}

/// Where one lesson sits for the learner: behind them, in front of them,
/// or not yet reachable. Only `next` is honestly startable — the composer
/// always plays a scenario's next unplayed depth, so there is no way to
/// jump ahead or replay a specific depth.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum LessonState {
    Completed,
    Next,
    Locked,
}

/// Every lesson in the pack, grouped for the Learn tab's browsable path.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct LearnPath {
    pub current_phase: u32,
    /// One section per run of consecutive scenarios at the same level, in
    /// stored order — the path's CEFR headings.
    pub sections: Vec<LearnSection>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct LearnSection {
    pub cefr_level: String,
    pub units: Vec<LearnUnit>,
}

/// One scenario as a unit on the path: its art and its lessons in depth
/// order.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct LearnUnit {
    pub scenario_id: String,
    pub label: String,
    /// Media path for `get_media`; empty when the unit is unillustrated.
    pub image: String,
    pub phase: u32,
    pub sequence: Option<u32>,
    pub lessons: Vec<LearnLesson>,
}

/// One node on the path — a lesson, with enough framing to draw it.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct LearnLesson {
    pub lesson_id: String,
    pub scenario_id: String,
    pub depth: u8,
    pub cefr_level: String,
    pub label: String,
    pub goal: String,
    pub summary: String,
    /// Media path for `get_media`; empty when the lesson is unillustrated.
    pub image: String,
    pub state: LessonState,
}

/// One lesson resolved for its intro screen: labels for everything it
/// introduces, revisits, and capstones, plus its art and state. Undeclared
/// (lifted-stub) lessons have empty blocks and the intro degrades to the
/// summary alone.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct LessonDetail {
    pub lesson_id: String,
    pub scenario_id: String,
    pub depth: u8,
    pub cefr_level: String,
    pub label: String,
    pub goal: String,
    pub summary: String,
    pub scene_setting: String,
    pub outro: String,
    /// Media path for `get_media`; empty when the lesson is unillustrated.
    pub image: String,
    pub scenario_label: String,
    pub scenario_image: String,
    pub introduces: LessonDetailIntroduces,
    pub revisits: LessonDetailRevisits,
    pub capstones: Vec<LessonDetailCapstone>,
    pub state: LessonState,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct LessonDetailIntroduces {
    pub grammar: Vec<SpecLabel>,
    pub functions: Vec<SpecLabel>,
    pub vocab: Vec<SpecLabel>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct LessonDetailRevisits {
    pub grammar: Vec<LabeledRevisit>,
    pub functions: Vec<LabeledRevisit>,
    pub vocab: Vec<LabeledRevisit>,
}

/// A revisited spec id with its name and the rung it is taken to.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct LabeledRevisit {
    pub id: String,
    pub label: String,
    pub demand: pack::Demand,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct LessonDetailCapstone {
    pub cando_id: String,
    pub label: String,
    pub demand: pack::Demand,
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

    /// Report a problem with a pack item — a wrong answer key, a confusing
    /// explanation, something that didn't render. `note` is the learner's
    /// own words. Stored in the event log so it survives offline, and
    /// ignored by the fold, so reporting never moves mastery.
    pub fn flag_item(&self, item_id: String, note: String) -> Result<(), CoreError> {
        // Stamped with the pack it was raised against: the same item id
        // can be fixed and re-shipped, so a flag without a version can't
        // be told apart from one already dealt with.
        let event = serde_json::json!({
            "type": "item_flagged",
            "item_id": item_id,
            "note": note,
            "pack_version": self.manifest()?.pack_version,
        });
        self.record_event(event.to_string())
    }

    /// Flags raised so far, newest first, as JSON objects. Backs the
    /// "reported problems" list.
    pub fn list_flags(&self) -> Result<Vec<String>, CoreError> {
        events::list_flags(&self.learner.lock().unwrap())
    }

    /// Just the flags as portable JSONL, for handing to the content
    /// authors. Deliberately narrower than `export_log`: reporting a typo
    /// shouldn't mean shipping your whole learning history.
    pub fn export_flags(&self) -> Result<String, CoreError> {
        events::export_flags(&self.learner.lock().unwrap())
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

    /// The whole vocabulary inventory as JSON: every spec lemma, the
    /// authored card for it when the pack has one, and the learner's SM-2
    /// state. `now` is unix seconds — `due_in_days` and `status` are
    /// relative to it, so they stay deterministic like every other fold.
    pub fn vocab_inventory(&self, now: i64) -> Result<String, CoreError> {
        let events = self.load_events()?;
        let pack_conn = self.pack.lock().unwrap();
        let spec = pack::load_spec(&pack_conn)?;
        let cards = pack::list_vocab_cards(&pack_conn)?;
        drop(pack_conn);
        let state = folds::fold(&events, &spec, now);

        let by_lemma: std::collections::HashMap<&str, &pack::VocabCardRow> = cards
            .iter()
            .map(|c| (c.lemma.as_str(), c))
            .collect();
        let today = model::unix_day(now);

        let entries: Vec<VocabEntry> = spec
            .vocab
            .iter()
            .map(|v| {
                let card = by_lemma.get(v.id.as_str());
                let srs = state.vocab.get(&v.id);
                VocabEntry {
                    lemma: v.id.clone(),
                    cefr_level: v.cefr_level.clone(),
                    pos: v.pos.clone(),
                    gloss: v.gloss.clone(),
                    item_id: card.map(|c| c.item_id.clone()),
                    front: card.map(|c| c.front.clone()),
                    back: card.map(|c| c.back.clone()),
                    example: card.and_then(|c| c.example.clone()),
                    example_gloss: card.and_then(|c| c.example_gloss.clone()),
                    repetitions: srs.map(|c| c.repetitions).unwrap_or(0),
                    reviews: srs.map(|c| c.reviews).unwrap_or(0),
                    interval_days: srs.map(|c| c.interval_days).unwrap_or(0),
                    ease_factor: srs.map(|c| c.ease_factor).unwrap_or(0.0),
                    due_in_days: srs.map(|c| c.due_day - today),
                    first_seen_days_ago: srs.map(|c| today - c.first_seen_day),
                    // Bands ported from the web app's vocab page, plus two
                    // this app needs: "new" for inventory the learner has
                    // never met (there, a card existed only once added),
                    // and "discovered" for a word a lesson put in front of
                    // them that they haven't practised yet.
                    status: match srs {
                        None => "new",
                        Some(c) if c.reviews == 0 => "discovered",
                        Some(c) if c.due_day <= today => "due",
                        Some(c) if c.interval_days < 14 => "learning",
                        Some(_) => "known",
                    }
                    .to_string(),
                }
            })
            .collect();

        serde_json::to_string(&entries).map_err(|e| CoreError::Storage {
            message: e.to_string(),
        })
    }

    /// The lesson the composer would choose right now, as a `LessonBrief`
    /// JSON object — or `null` when the learner has finished everything
    /// unlocked. `now` is unix seconds, as everywhere else.
    ///
    /// Deliberately separate from `compose_session`: the learner should see
    /// what a lesson is about before committing to it, and composing to
    /// find that out would burn the anti-repetition window on a session
    /// they might not start.
    pub fn next_lesson_brief(&self, now: i64) -> Result<String, CoreError> {
        let events = self.load_events()?;
        let spec = pack::load_spec(&self.pack.lock().unwrap())?;
        let state = folds::fold(&events, &spec, now);
        let brief =
            session::pick_scenario(&spec, &state, None).map(|(s, _)| brief_of(s, &spec, &state));
        serde_json::to_string(&brief).map_err(|e| CoreError::Storage {
            message: e.to_string(),
        })
    }

    /// The brief for one named scenario — what the recap shows after a
    /// session, where the scenario is already known. `null` if unknown.
    pub fn lesson_brief(&self, scenario_id: String, now: i64) -> Result<String, CoreError> {
        let events = self.load_events()?;
        let spec = pack::load_spec(&self.pack.lock().unwrap())?;
        let state = folds::fold(&events, &spec, now);
        let brief = spec
            .scenarios
            .iter()
            .find(|s| s.id == scenario_id)
            .map(|s| brief_of(s, &spec, &state));
        serde_json::to_string(&brief).map_err(|e| CoreError::Storage {
            message: e.to_string(),
        })
    }

    /// Every lesson in the pack as the Learn tab's path (`LearnPath`
    /// JSON): sections by consecutive CEFR level, one unit per scenario,
    /// each lesson with its state (`completed | next | locked`).
    /// `now` is unix seconds, as everywhere else.
    pub fn list_lessons(&self, now: i64) -> Result<String, CoreError> {
        let events = self.load_events()?;
        let pack_conn = self.pack.lock().unwrap();
        let spec = pack::load_spec(&pack_conn)?;
        let media = media_paths(&pack_conn)?;
        drop(pack_conn);
        let state = folds::fold(&events, &spec, now);
        serde_json::to_string(&learn_path(&spec, &state, &media)).map_err(|e| {
            CoreError::Storage {
                message: e.to_string(),
            }
        })
    }

    /// One lesson resolved for its intro screen (`LessonDetail` JSON):
    /// labels for what it introduces, revisits, and capstones, plus its
    /// art and state. `null` for an id the pack doesn't know.
    pub fn lesson_detail(&self, lesson_id: String, now: i64) -> Result<String, CoreError> {
        let events = self.load_events()?;
        let pack_conn = self.pack.lock().unwrap();
        let spec = pack::load_spec(&pack_conn)?;
        let media = media_paths(&pack_conn)?;
        drop(pack_conn);
        let state = folds::fold(&events, &spec, now);
        let detail = spec
            .lessons
            .iter()
            .find(|l| l.id == lesson_id)
            .map(|l| lesson_detail_of(l, &spec, &state, &media));
        serde_json::to_string(&detail).map_err(|e| CoreError::Storage {
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

/// Resolve a scenario against the spec's label tables and the learner's
/// history. Ids that the spec doesn't know fall back to themselves rather
/// than vanishing — a missing label is a content bug worth seeing.
fn brief_of(
    scenario: &pack::SpecScenario,
    spec: &pack::SpecData,
    state: &model::DerivedState,
) -> LessonBrief {
    let label_for = |id: &String, table: &[(&str, &str)]| SpecLabel {
        id: id.clone(),
        label: table
            .iter()
            .find(|(tid, _)| tid == id)
            .map(|(_, l)| *l)
            .filter(|l| !l.is_empty())
            .unwrap_or(id.as_str())
            .to_string(),
    };
    let grammar: Vec<(&str, &str)> = spec
        .grammar
        .iter()
        .map(|g| (g.id.as_str(), g.label.as_str()))
        .collect();
    let functions: Vec<(&str, &str)> = spec
        .functions
        .iter()
        .map(|f| (f.id.as_str(), f.label.as_str()))
        .collect();
    let progress = state.scenarios.get(&scenario.id);
    LessonBrief {
        scenario_id: scenario.id.clone(),
        cefr_level: scenario.cefr_level.clone(),
        label: if scenario.label.is_empty() {
            scenario.id.clone()
        } else {
            scenario.label.clone()
        },
        description: scenario.description.clone(),
        overview: scenario.overview.clone(),
        scene_setting: scenario.scene_setting.clone(),
        outro: scenario.outro.clone(),
        image: scenario.image.clone(),
        grammar: scenario
            .grammar_ids
            .iter()
            .map(|id| label_for(id, &grammar))
            .collect(),
        functions: scenario
            .function_ids
            .iter()
            .map(|id| label_for(id, &functions))
            .collect(),
        completed_depths: progress.map(|p| p.max_depth_completed).unwrap_or(0),
        depth_count: scenario.depth_count,
    }
}

/// The pack's media inventory as a path set — one query, checked many
/// times while building the path.
fn media_paths(conn: &Connection) -> Result<HashSet<String>, CoreError> {
    Ok(pack::list_media(conn)?.into_iter().map(|m| m.path).collect())
}

/// The conventional media path under `stem` iff the pack actually carries
/// the blob — "" otherwise, the same contract as `SpecScenario::image`.
/// Probed in the same (sorted) extension order the build sweeps.
fn conventional_image(media: &HashSet<String>, stem: &str) -> String {
    for ext in [".jpeg", ".jpg", ".png", ".webp"] {
        let path = format!("{stem}{ext}");
        if media.contains(&path) {
            return path;
        }
    }
    String::new()
}

/// A scenario's art: the authored path when the pack carries it, else
/// whatever sits at the conventional one. "" = unillustrated.
fn scenario_image(scenario: &pack::SpecScenario, media: &HashSet<String>) -> String {
    if !scenario.image.is_empty() && media.contains(&scenario.image) {
        return scenario.image.clone();
    }
    conventional_image(media, &format!("images/scenarios/{}", scenario.id))
}

/// Where `depth` sits given how far the learner has got. The composer
/// always plays the next unplayed depth (capped at the last one), so
/// exactly that depth is startable.
fn lesson_state(depth: u8, max_depth_completed: u8, depth_count: u8) -> LessonState {
    if depth <= max_depth_completed {
        LessonState::Completed
    } else if depth == (max_depth_completed + 1).min(depth_count) {
        LessonState::Next
    } else {
        LessonState::Locked
    }
}

/// Build the Learn tab's path: spec order (phase, sequence, id — as
/// stored), grouped into sections wherever the CEFR level changes.
/// Pure so the grouping and state rules are unit-testable without a pack.
fn learn_path(
    spec: &pack::SpecData,
    state: &model::DerivedState,
    media: &HashSet<String>,
) -> LearnPath {
    let mut sections: Vec<LearnSection> = Vec::new();
    for s in &spec.scenarios {
        let done = state
            .scenarios
            .get(&s.id)
            .map(|p| p.max_depth_completed)
            .unwrap_or(0);
        let lessons = spec
            .lessons
            .iter()
            .filter(|l| l.scenario_id == s.id)
            .map(|l| LearnLesson {
                lesson_id: l.id.clone(),
                scenario_id: s.id.clone(),
                depth: l.depth,
                cefr_level: l.cefr_level.clone(),
                label: if l.label.is_empty() {
                    l.id.clone()
                } else {
                    l.label.clone()
                },
                goal: l.goal.clone(),
                summary: l.summary.clone(),
                image: conventional_image(media, &format!("images/lessons/{}", l.id)),
                state: lesson_state(l.depth, done, s.depth_count),
            })
            .collect();
        let unit = LearnUnit {
            scenario_id: s.id.clone(),
            label: if s.label.is_empty() {
                s.id.clone()
            } else {
                s.label.clone()
            },
            image: scenario_image(s, media),
            phase: s.phase,
            sequence: s.sequence,
            lessons,
        };
        match sections.last_mut() {
            Some(section) if section.cefr_level == s.cefr_level => section.units.push(unit),
            _ => sections.push(LearnSection {
                cefr_level: s.cefr_level.clone(),
                units: vec![unit],
            }),
        }
    }
    LearnPath {
        current_phase: state.current_phase,
        sections,
    }
}

/// Resolve one lesson against the spec's label tables and the learner's
/// history. Ids the spec doesn't know fall back to themselves, like
/// `brief_of` — a missing label is a content bug worth seeing.
fn lesson_detail_of(
    lesson: &pack::SpecLesson,
    spec: &pack::SpecData,
    state: &model::DerivedState,
    media: &HashSet<String>,
) -> LessonDetail {
    let grammar: HashMap<&str, &str> = spec
        .grammar
        .iter()
        .map(|g| (g.id.as_str(), g.label.as_str()))
        .collect();
    let functions: HashMap<&str, &str> = spec
        .functions
        .iter()
        .map(|f| (f.id.as_str(), f.label.as_str()))
        .collect();
    // Vocab ids are the lemmas themselves; the gloss is the display name.
    let vocab: HashMap<&str, &str> = spec
        .vocab
        .iter()
        .map(|v| (v.id.as_str(), v.gloss.as_str()))
        .collect();
    let can_dos: HashMap<&str, &str> = spec
        .can_dos
        .iter()
        .map(|c| (c.id.as_str(), c.label.as_str()))
        .collect();
    let label_in = |table: &HashMap<&str, &str>, id: &String| SpecLabel {
        id: id.clone(),
        label: table
            .get(id.as_str())
            .copied()
            .filter(|l| !l.is_empty())
            .unwrap_or(id.as_str())
            .to_string(),
    };
    let revisit_in = |table: &HashMap<&str, &str>, r: &pack::LessonRevisit| {
        let labeled = label_in(table, &r.id);
        LabeledRevisit {
            id: labeled.id,
            label: labeled.label,
            demand: r.demand,
        }
    };

    let scenario = spec.scenarios.iter().find(|s| s.id == lesson.scenario_id);
    let done = state
        .scenarios
        .get(&lesson.scenario_id)
        .map(|p| p.max_depth_completed)
        .unwrap_or(0);
    let depth_count = scenario.map(|s| s.depth_count).unwrap_or(lesson.depth);

    LessonDetail {
        lesson_id: lesson.id.clone(),
        scenario_id: lesson.scenario_id.clone(),
        depth: lesson.depth,
        cefr_level: lesson.cefr_level.clone(),
        label: if lesson.label.is_empty() {
            lesson.id.clone()
        } else {
            lesson.label.clone()
        },
        goal: lesson.goal.clone(),
        summary: lesson.summary.clone(),
        scene_setting: lesson.scene_setting.clone(),
        outro: lesson.outro.clone(),
        image: conventional_image(media, &format!("images/lessons/{}", lesson.id)),
        scenario_label: scenario
            .map(|s| {
                if s.label.is_empty() {
                    s.id.clone()
                } else {
                    s.label.clone()
                }
            })
            .unwrap_or_else(|| lesson.scenario_id.clone()),
        scenario_image: scenario.map(|s| scenario_image(s, media)).unwrap_or_default(),
        introduces: LessonDetailIntroduces {
            grammar: lesson
                .introduces
                .grammar
                .iter()
                .map(|id| label_in(&grammar, id))
                .collect(),
            functions: lesson
                .introduces
                .functions
                .iter()
                .map(|id| label_in(&functions, id))
                .collect(),
            vocab: lesson
                .introduces
                .vocab
                .iter()
                .map(|id| label_in(&vocab, id))
                .collect(),
        },
        revisits: LessonDetailRevisits {
            grammar: lesson
                .revisits
                .grammar
                .iter()
                .map(|r| revisit_in(&grammar, r))
                .collect(),
            functions: lesson
                .revisits
                .functions
                .iter()
                .map(|r| revisit_in(&functions, r))
                .collect(),
            vocab: lesson
                .revisits
                .vocab
                .iter()
                .map(|r| revisit_in(&vocab, r))
                .collect(),
        },
        capstones: lesson
            .capstones
            .iter()
            .map(|c| {
                let labeled = label_in(&can_dos, &c.cando);
                LessonDetailCapstone {
                    cando_id: labeled.id,
                    label: labeled.label,
                    demand: c.demand,
                }
            })
            .collect(),
        state: lesson_state(lesson.depth, done, depth_count),
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

#[cfg(test)]
mod learn_path_tests {
    use super::*;

    fn scenario(id: &str, level: &str, sequence: u32, depth_count: u8) -> pack::SpecScenario {
        pack::SpecScenario {
            id: id.into(),
            cefr_level: level.into(),
            phase: 1,
            sequence: Some(sequence),
            depth_count,
            label: format!("{id} label"),
            ..Default::default()
        }
    }

    fn lesson(scenario_id: &str, depth: u8, level: &str) -> pack::SpecLesson {
        pack::SpecLesson {
            id: format!("{scenario_id}.d{depth}"),
            scenario_id: scenario_id.into(),
            depth,
            cefr_level: level.into(),
            label: format!("depth {depth}"),
            ..Default::default()
        }
    }

    fn spec() -> pack::SpecData {
        pack::SpecData {
            scenarios: vec![
                scenario("a0-01", "A0", 1, 2),
                scenario("a0-02", "A0", 2, 1),
                scenario("a1-01", "A1", 3, 1),
            ],
            lessons: vec![
                lesson("a0-01", 1, "A0"),
                lesson("a0-01", 2, "A0"),
                lesson("a0-02", 1, "A0"),
                lesson("a1-01", 1, "A1"),
            ],
            ..Default::default()
        }
    }

    fn states(path: &LearnPath, scenario_id: &str) -> Vec<LessonState> {
        path.sections
            .iter()
            .flat_map(|s| &s.units)
            .find(|u| u.scenario_id == scenario_id)
            .expect("unit")
            .lessons
            .iter()
            .map(|l| l.state)
            .collect()
    }

    #[test]
    fn groups_consecutive_levels_into_sections() {
        let path = learn_path(&spec(), &model::DerivedState::default(), &HashSet::new());
        let levels: Vec<&str> = path.sections.iter().map(|s| s.cefr_level.as_str()).collect();
        assert_eq!(levels, ["A0", "A1"]);
        let units: Vec<&str> = path.sections[0]
            .units
            .iter()
            .map(|u| u.scenario_id.as_str())
            .collect();
        assert_eq!(units, ["a0-01", "a0-02"]);
        assert_eq!(path.sections[0].units[0].lessons.len(), 2);
    }

    #[test]
    fn a_fresh_learner_has_every_first_depth_next_and_the_rest_locked() {
        let path = learn_path(&spec(), &model::DerivedState::default(), &HashSet::new());
        assert_eq!(states(&path, "a0-01"), [LessonState::Next, LessonState::Locked]);
        assert_eq!(states(&path, "a0-02"), [LessonState::Next]);
    }

    #[test]
    fn completing_a_depth_flips_states() {
        let ev: model::EvidenceEvent = serde_json::from_str(
            r#"{"type":"scenario_completed","at":1000,"scenario_id":"a0-01","depth":1}"#,
        )
        .unwrap();
        let spec = spec();
        let state = folds::fold(&[ev], &spec, 2000);
        let path = learn_path(&spec, &state, &HashSet::new());
        assert_eq!(
            states(&path, "a0-01"),
            [LessonState::Completed, LessonState::Next]
        );
        // The neighbour is untouched.
        assert_eq!(states(&path, "a0-02"), [LessonState::Next]);
    }

    #[test]
    fn a_finished_scenario_has_no_next() {
        // Past the last depth nothing is startable — completed throughout.
        assert_eq!(lesson_state(1, 2, 2), LessonState::Completed);
        assert_eq!(lesson_state(2, 2, 2), LessonState::Completed);
    }

    #[test]
    fn images_resolve_only_through_the_media_table() {
        let media: HashSet<String> = [
            "images/lessons/a0-01.d1.png".to_string(),
            "images/scenarios/a0-01.png".to_string(),
        ]
        .into();
        let path = learn_path(&spec(), &model::DerivedState::default(), &media);
        let unit = &path.sections[0].units[0];
        assert_eq!(unit.image, "images/scenarios/a0-01.png");
        assert_eq!(unit.lessons[0].image, "images/lessons/a0-01.d1.png");
        assert_eq!(unit.lessons[1].image, "");
        assert_eq!(path.sections[0].units[1].image, "");
    }

    #[test]
    fn detail_resolves_labels_and_serializes_lowercase() {
        let mut spec = spec();
        spec.grammar.push(pack::SpecGrammar {
            id: "gp1".into(),
            cefr_level: "A0".into(),
            label: "Un / una".into(),
            ..Default::default()
        });
        spec.vocab.push(pack::SpecVocab {
            id: "caffè".into(),
            cefr_level: "A0".into(),
            pos: "noun".into(),
            gloss: "coffee".into(),
        });
        spec.can_dos.push(pack::SpecCanDo {
            id: "a0.order".into(),
            cefr_level: "A0".into(),
            label: "Can order something".into(),
            ..Default::default()
        });
        spec.lessons[0].introduces.grammar = vec!["gp1".into(), "unknown_gp".into()];
        spec.lessons[0].revisits.vocab = vec![pack::LessonRevisit {
            id: "caffè".into(),
            demand: pack::Demand::Use,
        }];
        spec.lessons[0].capstones = vec![pack::LessonCapstone {
            cando: "a0.order".into(),
            demand: pack::Demand::Perform,
        }];

        let detail = lesson_detail_of(
            &spec.lessons[0].clone(),
            &spec,
            &model::DerivedState::default(),
            &HashSet::new(),
        );
        assert_eq!(detail.scenario_label, "a0-01 label");
        assert_eq!(detail.introduces.grammar[0].label, "Un / una");
        // An id the spec doesn't know falls back to itself.
        assert_eq!(detail.introduces.grammar[1].label, "unknown_gp");
        assert_eq!(detail.revisits.vocab[0].label, "coffee");
        assert_eq!(detail.capstones[0].label, "Can order something");
        assert_eq!(detail.state, LessonState::Next);

        let json = serde_json::to_value(&detail).unwrap();
        assert_eq!(json["state"], "next");
        assert_eq!(json["capstones"][0]["demand"], "perform");
        assert_eq!(json["revisits"]["vocab"][0]["demand"], "use");
    }
}
