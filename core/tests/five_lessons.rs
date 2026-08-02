//! Acceptance test for the first five A0 lessons: the closest thing to the
//! on-device experience that runs without a Mac.
//!
//! Gated on MAESTRO_PACK_PATH so `cargo test` stays hermetic:
//!   uv run python -m authoring.cli build --include-draft
//!   MAESTRO_PACK_PATH=../build/it.pack.sqlite cargo test --test five_lessons

use std::collections::HashSet;

use maestro_core::Core;
use serde_json::Value;

const LESSONS: [&str; 5] = [
    "a0-01-in-aereo",
    "a0-02-in-albergo",
    "a0-03-al-bar",
    "a0-04-in-giro",
    "a0-05-chiedere-aiuto",
];

fn open(tag: &str) -> Option<std::sync::Arc<Core>> {
    let pack_path = std::env::var_os("MAESTRO_PACK_PATH")?;
    let learner = std::env::temp_dir().join(format!("{tag}-{}.sqlite", std::process::id()));
    let _ = std::fs::remove_file(&learner);
    Some(
        Core::open(
            pack_path.to_string_lossy().into_owned(),
            learner.to_string_lossy().into_owned(),
        )
        .expect("open pack"),
    )
}

fn compose(core: &Core, scenario: &str, seed: u64) -> Value {
    let opts = format!(
        r#"{{"now":1754000000,"time_budget_minutes":15,"seed":{seed},"scenario_id":"{scenario}"}}"#
    );
    serde_json::from_str(&core.compose_session(opts).expect("compose")).expect("plan json")
}

/// Every lesson must produce a complete session: nothing starved, the
/// grammar it introduces taught before it is drilled, and no passage
/// question scheduled on its own (those only make sense inside a passage).
#[test]
fn every_lesson_composes_a_full_session() {
    let Some(core) = open("five-lessons") else {
        eprintln!("MAESTRO_PACK_PATH not set; skipping");
        return;
    };

    for scenario in LESSONS {
        for seed in [1u64, 7, 42] {
            let plan = compose(&core, scenario, seed);
            let ctx = format!("{scenario} seed {seed}");
            let acts = plan["activities"].as_array().expect("activities");

            assert_eq!(
                plan["shortfalls"].as_array().map(Vec::len),
                Some(0),
                "{ctx}: content ran out: {}",
                plan["shortfalls"]
            );
            // A fresh learner meets this grammar for the first time either
            // way; which name it goes by depends on whether the lesson
            // declares a manifest yet. Both teach before they drill, which
            // is what the ordering assertion below actually checks.
            assert!(
                plan["archetype"] == "introduction" || plan["archetype"] == "first_visit",
                "{ctx}: expected a teaching session, got {}",
                plan["archetype"]
            );

            let mut seen = HashSet::new();
            for a in acts {
                let id = a["item_id"].as_str().unwrap();
                let item_type = a["item_type"].as_str().unwrap();
                assert!(seen.insert(id), "{ctx}: {id} scheduled twice");
                assert!(
                    !item_type.ends_with("_question"),
                    "{ctx}: {id} is a passage question with no passage"
                );
            }

            // Teach before drilling: every grammar_card precedes every drill.
            let first_drill = acts
                .iter()
                .position(|a| a["item_type"].as_str().unwrap().starts_with("drill"));
            let last_card = acts
                .iter()
                .rposition(|a| a["slot"].as_str().unwrap() == "grammar_card");
            if let (Some(drill), Some(card)) = (first_drill, last_card) {
                assert!(card < drill, "{ctx}: drilled before teaching");
            }
            assert!(last_card.is_some(), "{ctx}: no grammar reference scheduled");

            // Reading and listening are separate slots, not one "receptive"
            // pick: with four listenings against six readings a shared slot
            // drew a reading most of the time, and a learner could go weeks
            // without hearing the language. Speaking is required for the
            // same reason — every full session hears Italian and says it.
            let slots: Vec<&str> = acts.iter().map(|a| a["slot"].as_str().unwrap()).collect();
            for required in [
                "grammar_card",
                "new_grammar_drill",
                "reading",
                "listening",
                "speaking",
                "vocab_review",
            ] {
                assert!(slots.contains(&required), "{ctx}: no {required} activity");
            }
        }
    }
}

/// The Learn tab's path must show every al-bar lesson with its art and
/// walk its states forward as depths complete; the intro screen resolves
/// labels for what the lesson teaches.
#[test]
fn learn_path_lists_lessons_with_art_and_state() {
    let Some(core) = open("learn-path") else {
        eprintln!("MAESTRO_PACK_PATH not set; skipping");
        return;
    };
    let now = 1754000000i64;

    let al_bar = |path: &Value| -> Value {
        path["sections"]
            .as_array()
            .expect("sections")
            .iter()
            .flat_map(|s| s["units"].as_array().expect("units"))
            .find(|u| u["scenario_id"] == "a0-03-al-bar")
            .expect("al-bar unit")
            .clone()
    };

    let path: Value =
        serde_json::from_str(&core.list_lessons(now).expect("list")).expect("path json");
    let unit = al_bar(&path);
    let lessons = unit["lessons"].as_array().expect("lessons");
    assert_eq!(lessons.len(), 3, "al-bar declares three depths");
    for lesson in lessons {
        let image = lesson["image"].as_str().unwrap();
        assert!(
            image.starts_with("images/lessons/a0-03-al-bar.d"),
            "lesson art missing from the media table: {lesson}"
        );
        assert!(core.get_media(image.to_string()).is_ok(), "{image} not fetchable");
    }
    let states: Vec<&str> = lessons.iter().map(|l| l["state"].as_str().unwrap()).collect();
    assert_eq!(states, ["next", "locked", "locked"]);

    // Completing depth 1 moves the path along.
    core.record_event(
        serde_json::json!({
            "type": "scenario_completed", "at": now,
            "scenario_id": "a0-03-al-bar", "depth": 1,
        })
        .to_string(),
    )
    .expect("record completion");
    let path: Value =
        serde_json::from_str(&core.list_lessons(now).expect("list")).expect("path json");
    let unit = al_bar(&path);
    let states: Vec<&str> = unit["lessons"]
        .as_array()
        .unwrap()
        .iter()
        .map(|l| l["state"].as_str().unwrap())
        .collect();
    assert_eq!(states, ["completed", "next", "locked"]);

    // The intro screen's detail: labels resolved, never raw ids.
    let detail: Value =
        serde_json::from_str(&core.lesson_detail("a0-03-al-bar.d1".into(), now).expect("detail"))
            .expect("detail json");
    assert_eq!(detail["state"], "completed");
    assert_eq!(detail["scenario_label"], "Al bar");
    assert!(!detail["image"].as_str().unwrap().is_empty());
    let grammar = detail["introduces"]["grammar"].as_array().expect("grammar");
    assert!(!grammar.is_empty(), "d1 introduces grammar");
    for g in grammar {
        assert_ne!(g["label"], g["id"], "grammar label fell back to the id: {g}");
    }
    let capstones = detail["capstones"].as_array().expect("capstones");
    assert!(!capstones.is_empty(), "d1 capstones a can-do");
    assert!(capstones[0]["label"].as_str().unwrap().starts_with("Can "));

    // An id the pack doesn't know is null, not an error.
    let unknown = core.lesson_detail("no-such.d9".into(), now).expect("unknown");
    assert_eq!(unknown, "null");
}

/// Working through the lessons must actually move the learner on: complete
/// one and the composer offers the next, all the way to lesson five.
#[test]
fn a_learner_progresses_through_all_five_lessons() {
    let Some(core) = open("five-lessons-progress") else {
        eprintln!("MAESTRO_PACK_PATH not set; skipping");
        return;
    };

    let mut now = 1754000000i64;
    for (i, expected) in LESSONS.iter().enumerate() {
        // Unpinned: whatever the composer offers next is what the learner sees.
        let opts = format!(r#"{{"now":{now},"time_budget_minutes":15,"seed":{}}}"#, i + 1);
        let plan: Value =
            serde_json::from_str(&core.compose_session(opts).expect("compose")).expect("json");
        assert_eq!(
            plan["scenario_id"], *expected,
            "lesson {}: composer offered the wrong scenario",
            i + 1
        );

        // Work through it: cards mark grammar introduced, drills score.
        for a in plan["activities"].as_array().unwrap() {
            let id = a["item_id"].as_str().unwrap();
            let item = core.get_item_json(id.to_string()).expect("item");
            let payload: Value = serde_json::from_str(&item).expect("payload json");
            let evidence = payload["evidence"].clone();
            let kind = if a["slot"] == "grammar_card" {
                "introduced"
            } else {
                "attempt"
            };
            let event = serde_json::json!({
                "type": kind,
                "at": now,
                "item_id": id,
                "outcome": if kind == "attempt" { Some("correct") } else { None },
                "modality": "writing",
                "evidence_class": "targeted",
                "evidence": evidence,
            });
            core.record_event(event.to_string()).expect("record");
        }
        core.record_event(
            serde_json::json!({
                "type": "scenario_completed", "at": now,
                "scenario_id": expected, "depth": 1,
            })
            .to_string(),
        )
        .expect("record completion");

        now += 86_400;
    }

    // The ten grammar points those lessons teach should now show mastery.
    let progress: Value =
        serde_json::from_str(&core.progress_summary(now).expect("progress")).expect("json");
    for gp in [
        "saluti",
        "polite_exp",
        "pronun_bas",
        "mi_chiamo",
        "num_0_20",
        "art_un_una",
        "vorrei",
        "art_il_la",
        "dove_e",
        "prep_place",
    ] {
        let state = &progress["grammar"][gp];
        assert!(
            !state.is_null() && state["introduced"] == true,
            "{gp} never introduced across five lessons"
        );
        // The progress screen renders display_name; if it falls back to the
        // id the learner is reading raw slugs.
        let name = state["display_name"].as_str().unwrap_or("");
        assert!(
            !name.is_empty() && name != gp,
            "{gp}: no display name — progress would show the id"
        );
    }

    for (id, cando) in progress["can_dos"].as_object().expect("can_dos") {
        let label = cando["label"].as_str().unwrap_or("");
        assert!(
            !label.is_empty() && label != id,
            "can-do {id}: no label — progress would show the id"
        );
    }
}
