//! The session composer: intersect pack × spec × learner state into an
//! ordered session plan. Deterministic given (state, options.seed).
//!
//! Ported semantics (curriculum.py): phase gating happens in the fold;
//! here: scenario choice, breadth-before-depth, archetype selection, and
//! weakness-weighted item selection with an anti-repetition window.

use std::collections::HashSet;

use crate::folds::{is_mastered, unlocked_grammar};
use crate::model::{
    unix_day, DerivedState, PlannedActivity, SessionOptions, SessionPlan, Shortfall,
};
use crate::pack::{ItemMeta, SpecData, SpecScenario};

const BREADTH_BEFORE_DEPTH: usize = 3;
const APPLICATION_THRESHOLD: f64 = 0.7;
/// Vocab-review cards per full session (decision #16's known gap, closed:
/// due SM-2 cards get a dedicated slot now that packs carry vocab items).
const VOCAB_REVIEW_COUNT: usize = 3;

/// SplitMix64 — tiny deterministic RNG, no dependency.
struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E3779B97F4A7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^ (z >> 31)
    }

    fn next_f64(&mut self) -> f64 {
        (self.next() >> 11) as f64 / (1u64 << 53) as f64
    }
}

pub fn compose(
    items: &[ItemMeta],
    spec: &SpecData,
    state: &DerivedState,
    opts: &SessionOptions,
) -> SessionPlan {
    let unlocked: HashSet<String> = unlocked_grammar(state, spec).into_iter().collect();

    // ---- scenario --------------------------------------------------------
    let scenario = pick_scenario(spec, state, opts.scenario_id.as_deref());

    // ---- target grammar --------------------------------------------------
    let mut target: Vec<String> = match &scenario {
        Some(s) => s
            .grammar_ids
            .iter()
            .filter(|g| unlocked.contains(*g))
            .cloned()
            .collect(),
        None => vec![],
    };
    if target.is_empty() {
        // Fall back to the weakest unlocked material anywhere.
        let mut all: Vec<String> = unlocked.iter().cloned().collect();
        all.sort_by(|a, b| {
            mastery_of(state, a)
                .partial_cmp(&mastery_of(state, b))
                .unwrap()
                .then(a.cmp(b))
        });
        target = all.into_iter().take(4).collect();
    } else {
        target.sort_by(|a, b| {
            mastery_of(state, a)
                .partial_cmp(&mastery_of(state, b))
                .unwrap()
                .then(a.cmp(b))
        });
    }

    // ---- archetype (curriculum.py pick_archetype) ------------------------
    let new_gps: Vec<&String> = target
        .iter()
        .filter(|g| !state.grammar.get(*g).map(|s| s.introduced).unwrap_or(false))
        .collect();
    let archetype = if !target.is_empty() && !new_gps.is_empty() {
        "introduction"
    } else if !target.is_empty() {
        let mastered = target
            .iter()
            .filter(|g| is_mastered(state.grammar.get(*g).and_then(|s| s.mastery)))
            .count();
        if mastered as f64 >= target.len() as f64 * APPLICATION_THRESHOLD {
            "application"
        } else {
            "consolidation"
        }
    } else {
        "consolidation"
    };

    // ---- slot layout by archetype and budget -----------------------------
    // (slot name, item-kind, count)
    let quick = opts.time_budget_minutes <= 5;
    let new_gp_ids: Vec<String> = new_gps.iter().map(|s| s.to_string()).collect();
    let mut slots: Vec<(&str, Kind, usize)> = if quick {
        vec![("drill", Kind::Drill, 6)]
    } else {
        match archetype {
            // Teach before drilling: one reference page per grammar point
            // being introduced, ahead of the drills that assume it.
            // Speaking rather than the general production slot: a learner
            // meeting this grammar for the first time has nothing to write
            // an open answer with, but saying the phrase out loud is
            // exactly the practice the material is for.
            "introduction" => vec![
                ("grammar_card", Kind::GrammarRef(new_gp_ids.clone()), new_gp_ids.len().max(1)),
                ("new_grammar_drill", Kind::DrillTargeting(new_gp_ids.clone()), 4),
                ("weakness_drill", Kind::Drill, 3),
                ("receptive", Kind::Receptive, 1),
                ("speaking", Kind::Speaking, 1),
            ],
            "application" => vec![
                ("receptive", Kind::Receptive, 1),
                ("drill", Kind::Drill, 4),
                ("production", Kind::Production, 1),
            ],
            _ => vec![
                ("weakness_drill", Kind::Drill, 7),
                ("receptive", Kind::Receptive, 1),
                ("production", Kind::Production, 1),
            ],
        }
    };
    // Vocab review closes every full session: due SM-2 cards first,
    // unseen cards to bootstrap the rotation when nothing is due.
    if !quick {
        slots.push(("vocab_review", Kind::VocabReview, VOCAB_REVIEW_COUNT));
    }

    // ---- selection -------------------------------------------------------
    let recent: HashSet<&String> = state.recent_item_ids.iter().collect();
    let mut rng = Rng(opts.seed ^ 0xA5A5_5A5A_DEAD_BEEF);
    let mut taken: HashSet<String> = HashSet::new();
    let mut activities = Vec::new();
    let mut shortfalls = Vec::new();

    for (slot, kind, count) in slots {
        let targeting: &[String] = match &kind {
            Kind::DrillTargeting(gps) | Kind::GrammarRef(gps) => gps,
            _ => &target,
        };
        let mut candidates: Vec<(&ItemMeta, f64)> = items
            .iter()
            .filter(|i| kind.matches(i))
            .filter(|i| !taken.contains(&i.id))
            .filter(|i| {
                matches!(
                    kind,
                    Kind::Receptive | Kind::Production | Kind::Speaking | Kind::VocabReview
                )
                    || i.grammar_ids.iter().any(|g| targeting.contains(g))
            })
            .filter(|i| i.grammar_ids.iter().all(|g| unlocked.contains(g)))
            .map(|i| {
                let w = match kind {
                    Kind::VocabReview => vocab_weight(state, i, opts.now),
                    _ => weakness_weight(state, i),
                };
                (i, w)
            })
            .collect();
        // Anti-repetition: prefer unseen; fall back to repeats only if the
        // slot would otherwise starve.
        let unseen: Vec<(&ItemMeta, f64)> = candidates
            .iter()
            .filter(|(i, _)| !recent.contains(&i.id))
            .cloned()
            .collect();
        if unseen.len() >= count {
            candidates = unseen;
        }
        let mut filled = 0usize;
        for _ in 0..count {
            let Some(pick) = weighted_pick(&mut rng, &candidates, &taken) else {
                break;
            };
            taken.insert(pick.id.clone());
            filled += 1;
            activities.push(PlannedActivity {
                item_id: pick.id.clone(),
                item_type: pick.item_type.clone(),
                slot: slot.to_string(),
            });
        }
        if filled < count {
            shortfalls.push(Shortfall {
                slot: slot.to_string(),
                requested: count as u32,
                filled: filled as u32,
            });
        }
    }

    SessionPlan {
        scenario_id: scenario.map(|s| s.id.clone()),
        archetype: archetype.to_string(),
        activities,
        target_grammar: target,
        shortfalls,
    }
}

enum Kind {
    Drill,
    DrillTargeting(Vec<String>),
    /// Reference pages for the listed grammar points.
    GrammarRef(Vec<String>),
    Receptive,
    Production,
    /// Production narrowed to speech, for archetypes where writing would
    /// be premature.
    Speaking,
    VocabReview,
}

impl Kind {
    /// Exact types, never prefixes: a passage's questions are separate items
    /// (`reading_question`, `listening_question`) that only make sense inside
    /// their parent, so a prefix match would schedule a comprehension question
    /// with no passage attached.
    fn matches(&self, item: &ItemMeta) -> bool {
        match self {
            Kind::Drill | Kind::DrillTargeting(_) => matches!(
                item.item_type.as_str(),
                "drill_cloze" | "drill_multiple_choice" | "drill_transform"
            ),
            Kind::GrammarRef(_) => item.item_type == "grammar_ref",
            Kind::Receptive => matches!(item.item_type.as_str(), "reading" | "listening"),
            Kind::Production => {
                matches!(item.item_type.as_str(), "writing_prompt" | "speaking_prompt")
            }
            Kind::Speaking => item.item_type == "speaking_prompt",
            Kind::VocabReview => item.item_type == "vocab_card",
        }
    }
}

/// Due cards dominate (more overdue -> heavier), then words met in a
/// lesson but never practised, then never-seen cards to bootstrap the
/// rotation; seen-and-not-due cards only appear under starvation.
///
/// Discovered words sit below real reviews on purpose: a single lesson can
/// introduce a dozen of them, and letting them outrank overdue cards on
/// sheer numbers would quietly stall the schedule.
fn vocab_weight(state: &DerivedState, item: &ItemMeta, now: i64) -> f64 {
    let today = unix_day(now);
    let mut weight: f64 = 0.0;
    for lemma in &item.vocab_ids {
        let w = match state.vocab.get(lemma) {
            Some(card) if card.reviews == 0 => 1.0,
            Some(card) if card.due_day <= today => {
                2.0 + ((today - card.due_day).min(30) as f64) / 10.0
            }
            Some(_) => 0.05,
            None => 0.75,
        };
        weight = weight.max(w);
    }
    weight
}

fn mastery_of(state: &DerivedState, gp: &str) -> f64 {
    state
        .grammar
        .get(gp)
        .and_then(|s| s.mastery)
        .unwrap_or(0.0)
}

/// 1/(mastery + 0.25): unseen/weak material ~4x more likely than mastered.
fn weakness_weight(state: &DerivedState, item: &ItemMeta) -> f64 {
    item.grammar_ids
        .iter()
        .map(|g| 1.0 / (mastery_of(state, g).max(0.0) + 0.25))
        .fold(1.0, f64::max)
}

fn weighted_pick<'a>(
    rng: &mut Rng,
    candidates: &[(&'a ItemMeta, f64)],
    taken: &HashSet<String>,
) -> Option<&'a ItemMeta> {
    let live: Vec<&(&ItemMeta, f64)> = candidates
        .iter()
        .filter(|(i, _)| !taken.contains(&i.id))
        .collect();
    let total: f64 = live.iter().map(|(_, w)| w).sum();
    if live.is_empty() || total <= 0.0 {
        return None;
    }
    let mut roll = rng.next_f64() * total;
    for (item, w) in &live {
        roll -= w;
        if roll <= 0.0 {
            return Some(item);
        }
    }
    Some(live.last().unwrap().0)
}

/// Least-completed scenario in the current phase; depth 2+ only after
/// breadth (>= 3 scenarios completed at depth 1) — curriculum.py semantics.
pub(crate) fn pick_scenario<'a>(
    spec: &'a SpecData,
    state: &DerivedState,
    override_id: Option<&str>,
) -> Option<&'a SpecScenario> {
    if let Some(id) = override_id {
        return spec.scenarios.iter().find(|s| s.id == id);
    }
    let in_phase: Vec<&SpecScenario> = spec
        .scenarios
        .iter()
        .filter(|s| s.phase <= state.current_phase)
        .collect();
    let breadth = state
        .scenarios
        .values()
        .filter(|s| s.max_depth_completed >= 1)
        .count();
    in_phase
        .into_iter()
        .filter(|s| {
            let done = state
                .scenarios
                .get(&s.id)
                .map(|p| p.max_depth_completed)
                .unwrap_or(0);
            // Something left to do at this scenario:
            done < s.depth_count.max(1)
                // ...and depth >1 requires breadth first.
                && (done == 0 || breadth >= BREADTH_BEFORE_DEPTH)
        })
        .min_by_key(|s| {
            (
                state
                    .scenarios
                    .get(&s.id)
                    .map(|p| p.completions)
                    .unwrap_or(0),
                s.phase,
                s.sequence.unwrap_or(u32::MAX),
                s.id.clone(),
            )
        })
}
