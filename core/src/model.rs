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
    pub grammar_mastered: u32,
    pub grammar_total: u32,
    pub functions_demonstrated: u32,
    pub functions_total: u32,
    pub applied: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DerivedState {
    pub grammar: std::collections::BTreeMap<String, GrammarState>,
    /// Correct productive/targeted uses per function id.
    pub functions: std::collections::BTreeMap<String, u32>,
    pub vocab: std::collections::BTreeMap<String, VocabCard>,
    pub scenarios: std::collections::BTreeMap<String, ScenarioState>,
    pub can_dos: std::collections::BTreeMap<String, CanDoState>,
    /// Highest CEFR level where >=90% of grammar mastered and functions
    /// demonstrated; "A0" floor.
    pub cefr_estimate: String,
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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionPlan {
    pub scenario_id: Option<String>,
    pub archetype: String,
    pub activities: Vec<PlannedActivity>,
    /// Grammar points this session targets, most-important first.
    pub target_grammar: Vec<String>,
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
