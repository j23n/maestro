//! Derived learner state as a fold over the event log.
//!
//! Semantics ported from the legacy Python (`learning/mastery.py`,
//! `vocab/srs.py`, `lessons/curriculum.py`) and pinned by the conformance
//! vectors. All time-dependent math takes `now` explicitly.

use std::collections::{BTreeMap, HashMap};

use crate::model::{
    cefr_rank, unix_day, CanDoState, CefrClassification, DerivedState, EvidenceClass,
    EvidenceEvent, EventType, GrammarState, Outcome, ScenarioState, VocabCard, CEFR_LEVELS,
    DAY_SECS,
};
use crate::pack::SpecData;

// mastery.py constants
const DECAY_BASE: f64 = 0.95;
const MASTERY_THRESHOLD: f64 = 0.8;
const MIN_EVIDENCE_MASS: f64 = 3.0;
const PER_GP_EVENT_CAP: usize = 50;
// functions: demonstrated at >= 3 correct uses (legacy behavior)
const FUNCTION_DEMONSTRATED_AT: u32 = 3;
// curriculum.py constants
const PHASE_GATE_THRESHOLD: usize = 5;
// can-do rollup thresholds (new; see decisions.md)
const CANDO_FRACTION: f64 = 0.8;
// CEFR classification. Deliberately *not* the legacy `_compute_cefr` gate,
// which required >=90% of a level's whole reference inventory to be
// mastered: with 351 grammar points in the Profilo and content for a
// fraction of them, that rule reports "A0" essentially forever. The level
// is a descriptive summary now, not a graduation threshold — can-dos carry
// progress. See `classify_cefr`.
const CEFR_ROUGH_FRACTION: f64 = 0.6;
const CEFR_MIN_ENCOUNTERED: usize = 3;
const CEFR_CONFIDENCE_HIGH: f64 = 0.5;
const CEFR_CONFIDENCE_MEDIUM: f64 = 0.2;
const RECENT_WINDOW: usize = 50;

pub fn mastery_label(score: Option<f64>) -> &'static str {
    match score {
        None => "new",
        Some(s) if s >= MASTERY_THRESHOLD => "consolidated",
        Some(s) if s >= 0.5 => "developing",
        Some(_) => "weak",
    }
}

pub fn is_mastered(score: Option<f64>) -> bool {
    matches!(score, Some(s) if s >= MASTERY_THRESHOLD)
}

/// Fold the full event log (ascending `at`) into derived state.
pub fn fold(events: &[EvidenceEvent], spec: &SpecData, now: i64) -> DerivedState {
    let mut state = DerivedState::default();

    // ---- grammar mastery -------------------------------------------------
    // Collect per-GP signed observations, newest first, capped at 50 per GP
    // (mastery.py's _EVENT_LIMIT), then decay-weight them.
    struct Obs {
        at: i64,
        weight: f64,
        sign: f64, // +1 correct, -1 incorrect, 0 partial
    }
    let mut per_gp: HashMap<&str, Vec<Obs>> = HashMap::new();
    let mut introduced: HashMap<&str, bool> = HashMap::new();

    for ev in events.iter().rev() {
        let at = ev.at.unwrap_or(now);
        match ev.event_type {
            EventType::Introduced => {
                for r in ev.evidence.iter().filter(|r| r.axis == "grammar") {
                    introduced.insert(r.id.as_str(), true);
                }
            }
            EventType::Attempt => {
                let Some(outcome) = ev.outcome else { continue };
                if outcome == Outcome::Skipped {
                    continue;
                }
                let class = ev.evidence_class.unwrap_or(EvidenceClass::Targeted);
                let sign = match outcome {
                    Outcome::Correct => 1.0,
                    Outcome::Incorrect => -1.0,
                    Outcome::Partial | Outcome::Skipped => 0.0,
                };
                for r in ev.evidence.iter().filter(|r| r.axis == "grammar") {
                    introduced.insert(r.id.as_str(), true);
                    let obs = per_gp.entry(r.id.as_str()).or_default();
                    if obs.len() < PER_GP_EVENT_CAP {
                        obs.push(Obs {
                            at,
                            weight: class.weight() * r.weight,
                            sign,
                        });
                    }
                }
            }
            EventType::ScenarioCompleted | EventType::LevelAssessed => {}
        }
    }

    for (gp, obs) in &per_gp {
        let mut num = 0.0;
        let mut denom = 0.0;
        for o in obs {
            let days_ago = (now - o.at) as f64 / DAY_SECS as f64;
            let decayed = o.weight * DECAY_BASE.powf(days_ago.max(0.0));
            num += o.sign * decayed;
            denom += decayed;
        }
        let mastery = if denom >= MIN_EVIDENCE_MASS {
            Some(num / denom)
        } else {
            None
        };
        state.grammar.insert(
            gp.to_string(),
            GrammarState {
                mastery,
                label: mastery_label(mastery).to_string(),
                introduced: true,
                evidence_mass: denom,
            },
        );
    }
    for (gp, _) in introduced {
        state.grammar.entry(gp.to_string()).or_insert(GrammarState {
            mastery: None,
            label: "new".to_string(),
            introduced: true,
            evidence_mass: 0.0,
        });
    }

    // ---- functions, vocab, scenarios, modality, recency ------------------
    let mut applied_can_dos: BTreeMap<String, bool> = BTreeMap::new();
    // Latest level test wins; events arrive ascending by `at`.
    let mut assessed_level: Option<String> = None;
    let mut assessed_at: Option<i64> = None;
    for ev in events {
        let at = ev.at.unwrap_or(now);
        match ev.event_type {
            EventType::Attempt => {
                if let Some(m) = &ev.modality {
                    *state.modality_evidence.entry(m.clone()).or_insert(0) += 1;
                }
                if let Some(id) = &ev.item_id {
                    state.recent_item_ids.push(id.clone());
                }
                let correct = ev.outcome == Some(Outcome::Correct);
                let class = ev.evidence_class.unwrap_or(EvidenceClass::Targeted);
                for r in &ev.evidence {
                    match r.axis.as_str() {
                        "function" => {
                            // Receptive exposure doesn't demonstrate a
                            // speech act; targeted/productive success does.
                            if correct && class != EvidenceClass::Receptive {
                                *state.functions.entry(r.id.clone()).or_insert(0) += 1;
                            }
                        }
                        "vocab" => {
                            if let Some(rating) = ev.srs_rating {
                                let card = state
                                    .vocab
                                    .entry(r.id.clone())
                                    .or_insert_with(|| VocabCard {
                                        ease_factor: 2.5,
                                        ..Default::default()
                                    });
                                sm2_review(card, rating, at);
                            }
                        }
                        "cando" => {
                            if correct {
                                applied_can_dos.insert(r.id.clone(), true);
                            }
                        }
                        _ => {}
                    }
                }
            }
            EventType::ScenarioCompleted => {
                let id = ev.scenario_id.clone().unwrap_or_default();
                let depth = ev.depth.unwrap_or(1);
                let entry = state
                    .scenarios
                    .entry(id)
                    .or_insert(ScenarioState {
                        completions: 0,
                        max_depth_completed: 0,
                    });
                entry.completions += 1;
                entry.max_depth_completed = entry.max_depth_completed.max(depth);
            }
            EventType::LevelAssessed => {
                if let Some(level) = &ev.assessed_level {
                    assessed_level = Some(level.clone());
                    assessed_at = Some(at);
                }
            }
            EventType::Introduced => {}
        }
    }
    let len = state.recent_item_ids.len();
    if len > RECENT_WINDOW {
        state.recent_item_ids.drain(..len - RECENT_WINDOW);
    }

    // ---- phase gating (curriculum.py get_current_phase) ------------------
    let mut phase = 1u32;
    loop {
        let completed_in_phase = spec
            .scenarios
            .iter()
            .filter(|s| s.phase == phase)
            .filter(|s| state.scenarios.contains_key(&s.id))
            .count();
        let has_next = spec.scenarios.iter().any(|s| s.phase == phase + 1);
        if completed_in_phase >= PHASE_GATE_THRESHOLD && has_next {
            phase += 1;
        } else {
            break;
        }
    }
    state.current_phase = phase;

    // ---- can-do rollup ---------------------------------------------------
    for cd in &spec.can_dos {
        let g_total = cd.grammar_ids.len() as u32;
        let f_total = cd.function_ids.len() as u32;
        let g_mastered = cd
            .grammar_ids
            .iter()
            .filter(|g| is_mastered(state.grammar.get(*g).and_then(|s| s.mastery)))
            .count() as u32;
        let f_demo = cd
            .function_ids
            .iter()
            .filter(|f| state.functions.get(*f).copied().unwrap_or(0) >= FUNCTION_DEMONSTRATED_AT)
            .count() as u32;
        let any_touched = cd
            .grammar_ids
            .iter()
            .any(|g| state.grammar.contains_key(g))
            || cd
                .function_ids
                .iter()
                .any(|f| state.functions.contains_key(f));
        let applied = applied_can_dos.contains_key(&cd.id);
        let frac_ok = |part: u32, total: u32| {
            total == 0 || (part as f64) >= (total as f64) * CANDO_FRACTION
        };
        let status = if applied && frac_ok(g_mastered, g_total) && frac_ok(f_demo, f_total) {
            "achieved"
        } else if any_touched {
            "in_progress"
        } else {
            "locked"
        };
        state.can_dos.insert(
            cd.id.clone(),
            CanDoState {
                status: status.to_string(),
                grammar_mastered: g_mastered,
                grammar_total: g_total,
                functions_demonstrated: f_demo,
                functions_total: f_total,
                applied,
            },
        );
    }

    // ---- CEFR classification ---------------------------------------------
    state.cefr = classify_cefr(&state, spec, assessed_level.as_deref(), assessed_at);
    state.cefr_estimate = state.cefr.level.clone();

    state
}

/// Rough CEFR classification from evidence, plus any level-test result.
///
/// Two things this deliberately does *not* do. It does not require a
/// fraction of the level's whole reference inventory — that inventory
/// describes the language, not the course, and gating on it makes levels
/// above the authored content unreachable. And it does not gate on
/// communicative functions: function counts are sparse and, being credited
/// per correct use rather than per assessment, are a weaker signal than
/// grammar mastery. Both are still reported, so demoting them here loses
/// no information.
///
/// The rule is: walk levels upward and claim the highest one where the
/// learner has met enough grammar points to judge (`CEFR_MIN_ENCOUNTERED`)
/// and has mastered most of the ones they met (`CEFR_ROUGH_FRACTION`).
/// Stop at the first level that fails, so levels are never skipped. A level
/// the spec has no inventory for is passed over rather than treated as a
/// failure, so a pack that starts at A1 doesn't pin everyone to A0.
///
/// `confidence` is the honesty layer: the same "A2" means something very
/// different off four grammar points than off forty, and the UI is expected
/// to show it.
fn classify_cefr(
    state: &DerivedState,
    spec: &SpecData,
    assessed: Option<&str>,
    assessed_at: Option<i64>,
) -> CefrClassification {
    let mut estimated = "A0";
    let mut evidence = (0u32, 0u32, 0u32); // mastered, encountered, total

    for level in CEFR_LEVELS {
        let gps: Vec<_> = spec
            .grammar
            .iter()
            .filter(|g| g.cefr_level == level)
            .collect();
        if gps.is_empty() {
            continue;
        }
        let encountered = gps
            .iter()
            .filter(|g| state.grammar.contains_key(&g.id))
            .count();
        let mastered = gps
            .iter()
            .filter(|g| is_mastered(state.grammar.get(&g.id).and_then(|s| s.mastery)))
            .count();

        let judgeable = encountered >= CEFR_MIN_ENCOUNTERED;
        let solid = mastered as f64 >= encountered as f64 * CEFR_ROUGH_FRACTION;
        if judgeable && solid {
            estimated = level;
            evidence = (mastered as u32, encountered as u32, gps.len() as u32);
        } else {
            break;
        }
    }

    let (mastered, encountered, total) = evidence;
    let coverage = if total == 0 {
        0.0
    } else {
        encountered as f64 / total as f64
    };
    let confidence = if encountered == 0 {
        "none"
    } else if coverage >= CEFR_CONFIDENCE_HIGH {
        "high"
    } else if coverage >= CEFR_CONFIDENCE_MEDIUM {
        "medium"
    } else {
        "low"
    };

    // A level test outranks the estimate only where it puts the learner
    // higher: evidence accumulated since the test should still be able to
    // move them up, and a test result shouldn't drag down someone who has
    // since demonstrated more.
    let est_rank = cefr_rank(estimated).unwrap_or(0);
    let (level, source) = match assessed.and_then(|a| cefr_rank(a).map(|r| (a, r))) {
        Some((a, r)) if r > est_rank => (a.to_string(), "assessed"),
        _ => (estimated.to_string(), "estimated"),
    };

    let functions_total = spec
        .functions
        .iter()
        .filter(|f| f.cefr_level == estimated)
        .count() as u32;
    let functions_demonstrated = spec
        .functions
        .iter()
        .filter(|f| {
            f.cefr_level == estimated
                && state.functions.get(&f.id).copied().unwrap_or(0) >= FUNCTION_DEMONSTRATED_AT
        })
        .count() as u32;

    CefrClassification {
        level,
        source: source.to_string(),
        estimated: estimated.to_string(),
        assessed: assessed.map(str::to_string),
        assessed_at,
        confidence: confidence.to_string(),
        grammar_mastered: mastered,
        grammar_encountered: encountered,
        grammar_total: total,
        functions_demonstrated,
        functions_total,
    }
}

/// SM-2, ported verbatim from `vocab/srs.py`.
fn sm2_review(card: &mut VocabCard, rating: u8, at: i64) {
    if rating < 3 {
        card.repetitions = 0;
        card.interval_days = 1;
    } else {
        card.repetitions += 1;
        card.interval_days = match card.repetitions {
            1 => 1,
            2 => 6,
            _ => (card.interval_days as f64 * card.ease_factor).round() as u32,
        };
    }
    let q = rating as f64;
    card.ease_factor += 0.1 - (5.0 - q) * (0.08 + (5.0 - q) * 0.02);
    card.ease_factor = card.ease_factor.max(1.3);
    card.due_day = unix_day(at) + card.interval_days as i64;
}

/// Grammar points whose prerequisites are all introduced
/// (curriculum.py get_unlocked_gps).
pub fn unlocked_grammar(state: &DerivedState, spec: &SpecData) -> Vec<String> {
    spec.grammar
        .iter()
        .filter(|g| {
            g.prerequisites
                .iter()
                .all(|p| state.grammar.get(p).map(|s| s.introduced).unwrap_or(false))
        })
        .map(|g| g.id.clone())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pack::SpecData;

    fn ev(json: &str) -> EvidenceEvent {
        serde_json::from_str(json).unwrap()
    }

    const NOW: i64 = 1_800_000_000;

    #[test]
    fn sm2_matches_python_port() {
        let mut card = VocabCard {
            ease_factor: 2.5,
            ..Default::default()
        };
        sm2_review(&mut card, 4, NOW);
        assert_eq!((card.repetitions, card.interval_days), (1, 1));
        assert!((card.ease_factor - 2.5).abs() < 1e-9);
        sm2_review(&mut card, 4, NOW + DAY_SECS);
        assert_eq!((card.repetitions, card.interval_days), (2, 6));
        // Interval uses the ease factor from *before* this review's ease
        // update (srs.py ordering): round(6 * 2.5) = 15.
        sm2_review(&mut card, 5, NOW + 7 * DAY_SECS);
        assert_eq!(card.interval_days, 15);
        sm2_review(&mut card, 2, NOW + 20 * DAY_SECS);
        assert_eq!((card.repetitions, card.interval_days), (0, 1));
    }

    #[test]
    fn mastery_needs_minimum_evidence_mass() {
        let spec = SpecData::default();
        let events = vec![ev(&format!(
            r#"{{"type":"attempt","at":{NOW},"outcome":"correct",
                "evidence":[{{"axis":"grammar","id":"gp1"}}]}}"#
        ))];
        let state = fold(&events, &spec, NOW);
        let gp = &state.grammar["gp1"];
        assert!(gp.mastery.is_none());
        assert!(gp.introduced);
        assert_eq!(gp.label, "new");
    }

    #[test]
    fn mastery_decays_and_weights_by_class() {
        let spec = SpecData::default();
        // 3 same-moment targeted corrects -> mass exactly 3.0, score 1.0.
        // (Staggered timestamps would decay the mass below the 3.0 floor —
        // that's the model working, not a bug.)
        let mut events: Vec<EvidenceEvent> = (0..3)
            .map(|_| {
                ev(&format!(
                    r#"{{"type":"attempt","at":{NOW},"outcome":"correct",
                        "evidence":[{{"axis":"grammar","id":"gp1"}}]}}"#
                ))
            })
            .collect();
        let state = fold(&events, &spec, NOW);
        assert!(is_mastered(state.grammar["gp1"].mastery));

        // One fresh productive incorrect (weight 1.5) drags it below 0.8.
        events.push(ev(&format!(
            r#"{{"type":"attempt","at":{NOW},"outcome":"incorrect",
                "evidence_class":"productive",
                "evidence":[{{"axis":"grammar","id":"gp1"}}]}}"#
        )));
        let state = fold(&events, &spec, NOW);
        let m = state.grammar["gp1"].mastery.unwrap();
        assert!(m < MASTERY_THRESHOLD && m > 0.0, "m={m}");

        // Same incorrect 60 days ago decays to irrelevance.
        let old = NOW - 60 * DAY_SECS;
        *events.last_mut().unwrap() = ev(&format!(
            r#"{{"type":"attempt","at":{old},"outcome":"incorrect",
                "evidence_class":"productive",
                "evidence":[{{"axis":"grammar","id":"gp1"}}]}}"#
        ));
        let state = fold(&events, &spec, NOW);
        assert!(is_mastered(state.grammar["gp1"].mastery));
    }

    #[test]
    fn functions_demonstrated_only_by_correct_nonreceptive_use() {
        let spec = SpecData::default();
        let mk = |class: &str, outcome: &str| {
            ev(&format!(
                r#"{{"type":"attempt","at":{NOW},"outcome":"{outcome}",
                    "evidence_class":"{class}",
                    "evidence":[{{"axis":"function","id":"f1"}}]}}"#
            ))
        };
        let events = vec![
            mk("targeted", "correct"),
            mk("productive", "correct"),
            mk("receptive", "correct"), // doesn't count
            mk("targeted", "incorrect"), // doesn't count
        ];
        let state = fold(&events, &spec, NOW);
        assert_eq!(state.functions["f1"], 2);
    }

    // ---- CEFR classification --------------------------------------------

    /// `n` grammar points at `level`, ids `{level}_0`… — enough inventory to
    /// make coverage fractions meaningful.
    fn spec_with_levels(levels: &[(&str, usize)]) -> SpecData {
        let mut spec = SpecData::default();
        for (level, n) in levels {
            for i in 0..*n {
                spec.grammar.push(crate::pack::SpecGrammar {
                    id: format!("{level}_{i}"),
                    cefr_level: level.to_string(),
                    prerequisites: vec![],
                });
            }
        }
        spec
    }

    /// Four same-moment correct attempts: enough mass (4.0) to clear
    /// MIN_EVIDENCE_MASS and score 1.0.
    fn mastered(gp: &str) -> Vec<EvidenceEvent> {
        (0..4)
            .map(|_| {
                ev(&format!(
                    r#"{{"type":"attempt","at":{NOW},"outcome":"correct",
                        "evidence":[{{"axis":"grammar","id":"{gp}"}}]}}"#
                ))
            })
            .collect()
    }

    #[test]
    fn cefr_is_rough_and_does_not_need_the_whole_inventory() {
        // 20 A1 points in the spec, learner has mastered 3. The legacy gate
        // wanted 90% of all 20; a rough classification should say A1.
        let spec = spec_with_levels(&[("A1", 20)]);
        let events: Vec<_> = ["A1_0", "A1_1", "A1_2"].iter().flat_map(|g| mastered(g)).collect();
        let state = fold(&events, &spec, NOW);
        assert_eq!(state.cefr.estimated, "A1");
        assert_eq!(state.cefr_estimate, "A1");
        assert_eq!(state.cefr.source, "estimated");
        assert_eq!(
            (state.cefr.grammar_mastered, state.cefr.grammar_encountered, state.cefr.grammar_total),
            (3, 3, 20)
        );
        // 3 of 20 encountered — the level is a guess and says so.
        assert_eq!(state.cefr.confidence, "low");
    }

    #[test]
    fn cefr_confidence_rises_with_coverage() {
        let spec = spec_with_levels(&[("A1", 6)]);
        let events: Vec<_> = ["A1_0", "A1_1", "A1_2", "A1_3"]
            .iter()
            .flat_map(|g| mastered(g))
            .collect();
        let state = fold(&events, &spec, NOW);
        assert_eq!(state.cefr.estimated, "A1");
        assert_eq!(state.cefr.confidence, "high"); // 4 of 6
    }

    #[test]
    fn cefr_needs_enough_encounters_to_judge() {
        // Two mastered points is not a level claim.
        let spec = spec_with_levels(&[("A1", 20)]);
        let events: Vec<_> = ["A1_0", "A1_1"].iter().flat_map(|g| mastered(g)).collect();
        let state = fold(&events, &spec, NOW);
        assert_eq!(state.cefr.estimated, "A0");
        assert_eq!(state.cefr.confidence, "none");
    }

    #[test]
    fn cefr_does_not_skip_levels() {
        // Strong A2 evidence, nothing at A1: the estimate stops below the gap.
        let spec = spec_with_levels(&[("A1", 10), ("A2", 10)]);
        let events: Vec<_> = ["A2_0", "A2_1", "A2_2", "A2_3"]
            .iter()
            .flat_map(|g| mastered(g))
            .collect();
        let state = fold(&events, &spec, NOW);
        assert_eq!(state.cefr.estimated, "A0");
    }

    #[test]
    fn cefr_passes_over_levels_the_spec_has_no_inventory_for() {
        // Pack starts at A1 — an absent A0 inventory must not pin the learner.
        let spec = spec_with_levels(&[("A1", 6)]);
        let events: Vec<_> = ["A1_0", "A1_1", "A1_2"].iter().flat_map(|g| mastered(g)).collect();
        let state = fold(&events, &spec, NOW);
        assert_eq!(state.cefr.estimated, "A1");
    }

    #[test]
    fn level_test_raises_the_level_but_never_lowers_it() {
        let spec = spec_with_levels(&[("A1", 6)]);
        let mut events: Vec<_> = ["A1_0", "A1_1", "A1_2"].iter().flat_map(|g| mastered(g)).collect();
        events.push(ev(&format!(
            r#"{{"type":"level_assessed","at":{NOW},"assessed_level":"B1"}}"#
        )));
        let state = fold(&events, &spec, NOW);
        assert_eq!(state.cefr.level, "B1");
        assert_eq!(state.cefr.source, "assessed");
        assert_eq!(state.cefr.assessed.as_deref(), Some("B1"));
        assert_eq!(state.cefr.assessed_at, Some(NOW));
        // The evidence-only estimate is preserved alongside.
        assert_eq!(state.cefr.estimated, "A1");

        // A test placing them *below* their demonstrated evidence doesn't
        // drag them down.
        let mut lower: Vec<_> = ["A1_0", "A1_1", "A1_2"].iter().flat_map(|g| mastered(g)).collect();
        lower.push(ev(&format!(
            r#"{{"type":"level_assessed","at":{NOW},"assessed_level":"A0"}}"#
        )));
        let state = fold(&lower, &spec, NOW);
        assert_eq!(state.cefr.level, "A1");
        assert_eq!(state.cefr.source, "estimated");
        assert_eq!(state.cefr.assessed.as_deref(), Some("A0"));
    }

    #[test]
    fn latest_level_test_wins() {
        let spec = SpecData::default();
        let events = vec![
            ev(&format!(
                r#"{{"type":"level_assessed","at":{NOW},"assessed_level":"B1"}}"#
            )),
            ev(&format!(
                r#"{{"type":"level_assessed","at":{},"assessed_level":"A2"}}"#,
                NOW + DAY_SECS
            )),
        ];
        let state = fold(&events, &spec, NOW + DAY_SECS);
        assert_eq!(state.cefr.assessed.as_deref(), Some("A2"));
        assert_eq!(state.cefr.level, "A2");
    }

    #[test]
    fn level_assessed_requires_a_known_level() {
        let bad = ev(r#"{"type":"level_assessed","assessed_level":"Z9"}"#);
        assert!(bad.validate().is_err());
        let missing = ev(r#"{"type":"level_assessed"}"#);
        assert!(missing.validate().is_err());
        let ok = ev(r#"{"type":"level_assessed","assessed_level":"A2"}"#);
        assert!(ok.validate().is_ok());
    }
}
