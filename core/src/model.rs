//! Typed shapes crossing the core boundary: evidence events (in), derived
//! state and session plans (out). Everything is serde-JSON at the FFI.
//!
//! Event schema is the contract from docs/plans/03-implementation-plan.md §4,
//! made concrete. Events are append-only; `at` (unix seconds) may be set by
//! the caller (tests, imports) and defaults to insertion time.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventType {
    /// A scored attempt at a pack item.
    Attempt,
    /// Material was presented (grammar card viewed); evidence ids are
    /// marked introduced without correctness signal.
    Introduced,
    /// A scenario session was completed at a depth.
    ScenarioCompleted,
    /// The learner reported a problem with a pack item: a wrong key, a
    /// confusing explanation, something that didn't render. Carries
    /// `item_id` and a free-text `note`. Recorded in the same log as
    /// everything else so it survives offline, but deliberately inert —
    /// the fold ignores it, so reporting a problem never moves mastery.
    ItemFlagged,
    /// An explicit CEFR level result — a placement or level test, or a
    /// trusted self-report. Carries `assessed_level`; `item_id` may name
    /// the test. No such producer ships yet: the event exists so a future
    /// level test has somewhere to land without a schema migration, and so
    /// the fold already knows how to prefer it over its own estimate.
    LevelAssessed,
}

/// CEFR levels, low to high. The order is load-bearing: `cefr_rank` drives
/// both the no-skipping rule in the estimate and assessed-vs-estimated
/// reconciliation.
pub const CEFR_LEVELS: [&str; 6] = ["A0", "A1", "A2", "B1", "B2", "C1"];

pub fn cefr_rank(level: &str) -> Option<usize> {
    CEFR_LEVELS.iter().position(|l| *l == level)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Outcome {
    Correct,
    Partial,
    Incorrect,
    Skipped,
}

/// How strong the evidence is, per the mastery model ported from
/// `learning/mastery.py`: productive use > targeted drills > receptive.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceClass {
    Targeted,
    Productive,
    Receptive,
}

impl EvidenceClass {
    pub fn weight(self) -> f64 {
        match self {
            EvidenceClass::Targeted => 1.0,
            EvidenceClass::Productive => 1.5,
            EvidenceClass::Receptive => 0.5,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvidenceRef {
    /// grammar | function | vocab | cando
    pub axis: String,
    pub id: String,
    #[serde(default = "default_weight")]
    pub weight: f64,
}

fn default_weight() -> f64 {
    1.0
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvidenceEvent {
    #[serde(rename = "type")]
    pub event_type: EventType,
    /// Unix seconds. Defaulted to insertion time by `record_event`.
    #[serde(default)]
    pub at: Option<i64>,
    #[serde(default)]
    pub item_id: Option<String>,
    #[serde(default)]
    pub pack_version: Option<String>,
    #[serde(default)]
    pub modality: Option<String>,
    #[serde(default)]
    pub evidence_class: Option<EvidenceClass>,
    #[serde(default)]
    pub outcome: Option<Outcome>,
    #[serde(default)]
    pub evidence: Vec<EvidenceRef>,
    /// The learner's actual answer; stays on device.
    #[serde(default)]
    pub response: Option<String>,
    /// SM-2 rating 1–5, applied to this event's vocab evidence refs.
    #[serde(default)]
    pub srs_rating: Option<u8>,
    #[serde(default)]
    pub scenario_id: Option<String>,
    #[serde(default)]
    pub depth: Option<u8>,
    /// deterministic | pre_authored | llm — where any feedback came from.
    #[serde(default)]
    pub feedback_source: Option<String>,
    /// CEFR level from a level test (`LevelAssessed` events only).
    #[serde(default)]
    pub assessed_level: Option<String>,
    /// What the learner said was wrong (`ItemFlagged` events only).
    #[serde(default)]
    pub note: Option<String>,
}

impl EvidenceEvent {
    pub fn validate(&self) -> Result<(), String> {
        match self.event_type {
            EventType::Attempt => {
                if self.outcome.is_none() {
                    return Err("attempt event requires outcome".into());
                }
                if self.evidence.is_empty() {
                    return Err("attempt event requires evidence".into());
                }
            }
            EventType::Introduced => {
                if self.evidence.is_empty() {
                    return Err("introduced event requires evidence".into());
                }
            }
            EventType::ScenarioCompleted => {
                if self.scenario_id.is_none() {
                    return Err("scenario_completed requires scenario_id".into());
                }
            }
            EventType::ItemFlagged => {
                if self.item_id.is_none() {
                    return Err("item_flagged requires item_id".into());
                }
            }
            EventType::LevelAssessed => match self.assessed_level.as_deref() {
                None => return Err("level_assessed requires assessed_level".into()),
                Some(l) if cefr_rank(l).is_none() => {
                    return Err(format!("level_assessed: unknown CEFR level {l:?}"));
                }
                Some(_) => {}
            },
        }
        if let Some(r) = self.srs_rating {
            if !(1..=5).contains(&r) {
                return Err("srs_rating must be 1-5".into());
            }
        }
        for e in &self.evidence {
            if !matches!(e.axis.as_str(), "grammar" | "function" | "vocab" | "cando") {
                return Err(format!("unknown evidence axis: {}", e.axis));
            }
        }
        Ok(())
    }
}

// --------------------------------------------------------------------------
// Derived state (output of folds::fold)

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GrammarState {
    /// None until evidence mass >= MIN_EVIDENCE_MASS.
    pub mastery: Option<f64>,
    /// new | weak | developing | consolidated (labels from mastery.py).
    pub label: String,
    /// The grammar point's human-readable name, from the spec. Falls back
    /// to the id on bundles built before labels shipped — the UI shows
    /// this, never the id.
    pub display_name: String,
    pub introduced: bool,
    pub evidence_mass: f64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct VocabCard {
    pub repetitions: u32,
    pub interval_days: u32,
    pub ease_factor: f64,
    /// Unix day (days since epoch) of the next due review.
    pub due_day: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScenarioState {
    pub completions: u32,
    pub max_depth_completed: u8,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CanDoState {
    /// locked | in_progress | achieved
    pub status: String,
    /// The can-do statement, from the spec ("Can greet people…"). Falls
    /// back to the id on pre-label bundles.
    pub label: String,
    pub grammar_mastered: u32,
    pub grammar_total: u32,
    pub functions_demonstrated: u32,
    pub functions_total: u32,
    pub applied: bool,
}

/// A rough, descriptive CEFR classification — deliberately *not* a gate.
///
/// Can-do descriptors are the learner-facing progress spine (`can_dos`);
/// this is the one-line summary that sits underneath them. It answers
/// "roughly where is this learner?" from whatever evidence exists, and
/// says how much evidence that is, rather than withholding a level until
/// a graduation threshold is met.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CefrClassification {
    /// The working level: the assessed level when a level test has put the
    /// learner higher than their evidence has, otherwise the estimate.
    pub level: String,
    /// Where `level` came from: "estimated" | "assessed".
    pub source: String,
    /// Estimated from evidence alone, ignoring any level test.
    pub estimated: String,
    /// Most recent `LevelAssessed` result, if any.
    pub assessed: Option<String>,
    pub assessed_at: Option<i64>,
    /// How much of `estimated`'s inventory the estimate rests on:
    /// "none" | "low" | "medium" | "high". Display this next to the level —
    /// a level derived from four grammar points should not look like a
    /// level derived from forty.
    pub confidence: String,
    /// Evidence behind `estimated`, at that level.
    pub grammar_mastered: u32,
    pub grammar_encountered: u32,
    pub grammar_total: u32,
    /// Reported alongside, but not part of the level decision — see
    /// `folds::classify_cefr`.
    pub functions_demonstrated: u32,
    pub functions_total: u32,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DerivedState {
    pub grammar: std::collections::BTreeMap<String, GrammarState>,
    /// Correct productive/targeted uses per function id.
    pub functions: std::collections::BTreeMap<String, u32>,
    pub vocab: std::collections::BTreeMap<String, VocabCard>,
    pub scenarios: std::collections::BTreeMap<String, ScenarioState>,
    pub can_dos: std::collections::BTreeMap<String, CanDoState>,
    /// Rough working level — mirrors `cefr.level`, kept as a flat field so
    /// callers that only want the one-word answer don't have to reach into
    /// the classification.
    pub cefr_estimate: String,
    /// The classification behind `cefr_estimate`, including how much
    /// evidence it rests on and whether a level test contributed.
    pub cefr: CefrClassification,
    /// Attempt counts per modality — the honesty layer behind the estimate.
    pub modality_evidence: std::collections::BTreeMap<String, u32>,
    pub current_phase: u32,
    /// Item ids of recent attempts (anti-repetition window).
    pub recent_item_ids: Vec<String>,
}

// --------------------------------------------------------------------------
// Session plan (output of session::compose)

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlannedActivity {
    pub item_id: String,
    pub item_type: String,
    /// Why the composer picked it (slot name, e.g. "new_grammar_drill",
    /// "weakness_drill", "receptive", "vocab_review").
    pub slot: String,
}

/// A slot the composer could not fill completely — the pack ran out of
/// eligible items. Surfaced so the shell can say "content ran out" instead
/// of silently presenting a short session.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Shortfall {
    pub slot: String,
    pub requested: u32,
    pub filled: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionPlan {
    pub scenario_id: Option<String>,
    pub archetype: String,
    pub activities: Vec<PlannedActivity>,
    /// Grammar points this session targets, most-important first.
    pub target_grammar: Vec<String>,
    /// Slots that came up short, in layout order. Empty on a full session.
    #[serde(default)]
    pub shortfalls: Vec<Shortfall>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SessionOptions {
    /// Unix seconds "now" — explicit so composition is deterministic.
    pub now: i64,
    /// 5 = quick queue session, 15 = full session (default).
    #[serde(default = "default_budget")]
    pub time_budget_minutes: u32,
    #[serde(default)]
    pub scenario_id: Option<String>,
    /// RNG seed for reproducible selection.
    #[serde(default)]
    pub seed: u64,
}

fn default_budget() -> u32 {
    15
}

pub const DAY_SECS: i64 = 86_400;

pub fn unix_day(unix_secs: i64) -> i64 {
    unix_secs.div_euclid(DAY_SECS)
}

// --------------------------------------------------------------------------
// The LLM feedback-job contract (plan §2.1). The core owns the queue and
// the fold-back; making the network call is the shell's job. Offline-first:
// submissions queue while there's no backend and drain when one appears.

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FeedbackJobRequest {
    /// writing_feedback | speaking_feedback | mistake_explanation —
    /// matches the prompt template + eval task name.
    pub kind: String,
    pub item_id: String,
    /// The learner's submission (writing text, speaking transcript, or
    /// the wrong answer to explain). Stays on device until a backend is
    /// explicitly asked to look at it.
    pub submission: String,
    /// Minimal extra prompt context (weakness tags, item prompt) — keep
    /// small on purpose; the privacy ledger shows exactly this.
    #[serde(default)]
    pub context: serde_json::Value,
}

impl FeedbackJobRequest {
    pub fn validate(&self) -> Result<(), String> {
        if !matches!(
            self.kind.as_str(),
            "writing_feedback" | "speaking_feedback" | "mistake_explanation"
        ) {
            return Err(format!("unknown feedback kind: {}", self.kind));
        }
        if self.item_id.is_empty() {
            return Err("feedback job requires item_id".into());
        }
        if self.submission.is_empty() {
            return Err("feedback job requires a submission".into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FeedbackResult {
    /// The feedback text to show the learner (already parsed/validated
    /// by the shell against the task's output schema).
    pub feedback_text: String,
    /// Evidence to fold back into the learner model, if the feedback
    /// carries a verdict (e.g. rubric grading). `feedback_source` is
    /// stamped with the backend name by `complete_feedback_job`.
    #[serde(default)]
    pub evidence_event: Option<EvidenceEvent>,
}
