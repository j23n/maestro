//! The whole A0 arc, played end to end.
//!
//! `closes_a_cando` proves one lesson can close one can-do. This proves
//! the band: thirty-nine lessons in curriculum order, and by the end every
//! A0 descriptor the spec claims is *achieved*, not merely touched. It is
//! the acceptance test for the closure contract — the same property
//! `validate --coverage --band A0` checks on the content, checked here on
//! the runtime that has to deliver it.
//!
//! Gated on MAESTRO_PACK_PATH so `cargo test` stays hermetic:
//!   uv run python -m authoring.cli build --include-draft
//!   MAESTRO_PACK_PATH=../build/it.pack.sqlite cargo test --test closes_a0

use std::collections::BTreeMap;

use maestro_core::Core;
use serde_json::Value;

const DAY: i64 = 86_400;
const START: i64 = 1_754_000_000;

const SCENARIOS: [&str; 13] = [
    "a0-01-in-aereo",
    "a0-02-in-albergo",
    "a0-03-al-bar",
    "a0-04-in-giro",
    "a0-05-chiedere-aiuto",
    "a0-06-a-pranzo",
    "a0-07-mi-piace",
    "a0-08-i-numeri-grandi",
    "a0-09-in-viaggio",
    "a0-10-conoscere-qualcuno",
    "a0-11-un-problema",
    "a0-12-ultimo-giorno",
    "a0-13-ripasso",
];

fn open(tag: &str) -> Option<std::sync::Arc<Core>> {
    let pack_path = std::env::var_os("MAESTRO_PACK_PATH")?;
    // Per-test file: the two tests run concurrently in one process, and a
    // shared learner db locks one of them out.
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

/// Play one lesson the way the shell does: a reference teaches, everything
/// else is attempted at the rung the pack authored for it, and the session
/// closes with a `scenario_completed` carrying its depth.
fn play(core: &Core, scenario: &str, depth: u8, now: i64) -> Value {
    let plan: Value = serde_json::from_str(
        &core
            .compose_session(format!(
                r#"{{"now":{now},"time_budget_minutes":15,"seed":{depth},"scenario_id":"{scenario}"}}"#
            ))
            .expect("compose"),
    )
    .expect("plan json");

    for a in plan["activities"].as_array().expect("activities") {
        let id = a["item_id"].as_str().unwrap();
        let item: Value = serde_json::from_str(&core.get_item_json(id.into()).unwrap()).unwrap();
        let evidence = item["evidence"].to_string();
        let class = match item["demand"].as_str() {
            Some("meet") => "receptive",
            Some("perform") => "productive",
            _ => "targeted",
        };
        if a["item_type"] == "grammar_ref" {
            core.record_event(format!(
                r#"{{"type":"introduced","at":{now},"evidence":{evidence}}}"#
            ))
            .unwrap();
            continue;
        }
        core.record_event(format!(
            r#"{{"type":"attempt","at":{now},"item_id":"{id}","outcome":"correct",
                 "modality":"writing","evidence_class":"{class}","evidence":{evidence}}}"#
        ))
        .unwrap();
    }
    core.record_event(format!(
        r#"{{"type":"scenario_completed","at":{now},"scenario_id":"{scenario}","depth":{depth}}}"#
    ))
    .unwrap();
    plan
}

#[test]
fn a_learner_who_finishes_a0_can_do_everything_a0_claims() {
    let Some(core) = open("closes-a0") else {
        eprintln!("MAESTRO_PACK_PATH not set; skipping");
        return;
    };

    let mut now = START;
    let mut lessons = 0;
    for scenario in SCENARIOS {
        for depth in 1..=3u8 {
            let plan = play(&core, scenario, depth, now);
            assert_eq!(
                plan["lesson_id"],
                format!("{scenario}.d{depth}"),
                "{scenario} depth {depth} composed from the wrong lesson"
            );
            assert!(
                !plan["activities"].as_array().unwrap().is_empty(),
                "{scenario}.d{depth} composed an empty session"
            );
            lessons += 1;
            now += DAY;
        }
    }
    assert_eq!(lessons, 39, "the A0 arc is thirty-nine lessons");

    // Every A0 descriptor, achieved — not "in_progress", which is what a
    // capstone with an untaught decomposition leaves behind.
    let progress: Value =
        serde_json::from_str(&core.progress_summary(now).expect("progress")).expect("json");
    let mut unclosed: BTreeMap<String, Value> = BTreeMap::new();
    for (id, state) in progress["can_dos"].as_object().expect("can_dos") {
        if !id.starts_with("a0.") {
            continue;
        }
        if state["status"] != "achieved" {
            unclosed.insert(id.clone(), state.clone());
        }
    }
    assert!(
        unclosed.is_empty(),
        "a learner played every A0 lesson and these can-dos still will not \
         close — the app cannot tell them what they can now do:\n{}",
        serde_json::to_string_pretty(&unclosed).unwrap()
    );
}

/// The arc has to hold together unpinned too: left to itself the composer
/// must walk the scenarios in curriculum order, not jump around.
#[test]
fn the_composer_walks_the_arc_in_order() {
    let Some(core) = open("a0-in-order") else {
        eprintln!("MAESTRO_PACK_PATH not set; skipping");
        return;
    };

    let mut now = START;
    for (i, expected) in SCENARIOS.iter().enumerate() {
        let plan: Value = serde_json::from_str(
            &core
                .compose_session(format!(
                    r#"{{"now":{now},"time_budget_minutes":15,"seed":{}}}"#,
                    i + 1
                ))
                .expect("compose"),
        )
        .expect("plan json");
        assert_eq!(
            plan["scenario_id"], *expected,
            "lesson {}: the composer offered the wrong scenario",
            i + 1
        );
        for depth in 1..=3u8 {
            play(&core, expected, depth, now);
            now += DAY;
        }
    }
}
