//! The loop, end to end: play a lesson's three framings against the real
//! pack and watch a can-do actually close.
//!
//! This is the property the whole lesson design exists for, and until the
//! capstone item type shipped it was unreachable — no authored item
//! carried `axis: cando`, so `applied` was false for all 68 descriptors
//! forever and the Progress tab could never show a single achievement.
//!
//! Gated on MAESTRO_PACK_PATH so `cargo test` stays hermetic:
//!   uv run python -m authoring.cli build --include-draft
//!   MAESTRO_PACK_PATH=../build/it.pack.sqlite cargo test --test closes_a_cando

use maestro_core::Core;
use serde_json::Value;

const CANDO: &str = "a0.order_something";
const SCENARIO: &str = "a0-03-al-bar";
const DAY: i64 = 86_400;

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

fn cando_state(core: &Core, now: i64) -> Value {
    let progress: Value =
        serde_json::from_str(&core.progress_summary(now).expect("progress")).unwrap();
    progress["can_dos"][CANDO].clone()
}

/// Play one depth as the shell does: cards teach, everything else is
/// attempted at the rung the pack authored, and the session closes with a
/// `scenario_completed` carrying its depth.
fn play(core: &Core, depth: u8, now: i64) -> Value {
    let plan: Value = serde_json::from_str(
        &core
            .compose_session(format!(
                r#"{{"now":{now},"time_budget_minutes":15,"seed":{depth},"scenario_id":"{SCENARIO}"}}"#
            ))
            .expect("compose"),
    )
    .unwrap();
    assert_eq!(plan["depth"], depth, "expected depth {depth}: {plan}");

    for a in plan["activities"].as_array().unwrap() {
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
        r#"{{"type":"scenario_completed","at":{now},"scenario_id":"{SCENARIO}","depth":{depth}}}"#
    ))
    .unwrap();
    plan
}

#[test]
fn three_framings_of_one_lesson_close_a_cando() {
    let Some(core) = open("closes-cando") else {
        eprintln!("MAESTRO_PACK_PATH not set; skipping");
        return;
    };
    let start = 1_754_000_000i64;

    // Every depth is a real lesson: composed from its manifest, and ending
    // on the capstone that is the point of it.
    let mut plans = Vec::new();
    for depth in 1..=3u8 {
        let plan = play(&core, depth, start + (depth as i64 - 1) * DAY);
        assert_eq!(
            plan["lesson_id"],
            format!("{SCENARIO}.d{depth}"),
            "depth {depth} must compose from its own lesson"
        );
        let last = plan["activities"].as_array().unwrap().last().unwrap();
        assert_eq!(
            last["slot"], "capstone",
            "a lesson ends on the thing it was for: {plan}"
        );
        plans.push(plan);
    }

    // The first visit teaches; the later ones come back to it harder.
    assert_eq!(plans[0]["archetype"], "first_visit");
    assert_eq!(plans[1]["archetype"], "deeper_visit");
    assert!(
        plans[0]["activities"]
            .as_array()
            .unwrap()
            .iter()
            .any(|a| a["slot"] == "grammar_card"),
        "the first visit must teach before it drills: {}",
        plans[0]
    );
    for later in &plans[1..] {
        assert!(
            later["activities"]
                .as_array()
                .unwrap()
                .iter()
                .all(|a| a["slot"] != "grammar_card"),
            "a return visit re-teaches nothing: {later}"
        );
        assert!(
            later["activities"]
                .as_array()
                .unwrap()
                .iter()
                .any(|a| a["slot"] == "revisit"),
            "a return visit comes back to something: {later}"
        );
    }

    // The capstones rise: the last one is the unscaffolded pass, and the
    // pack withholds its target so there is nothing on screen to copy.
    let capstone_of = |plan: &Value| -> String {
        plan["activities"]
            .as_array()
            .unwrap()
            .iter()
            .find(|a| a["slot"] == "capstone")
            .unwrap()["item_id"]
            .as_str()
            .unwrap()
            .to_string()
    };
    assert_eq!(capstone_of(&plans[2]), "task.al_bar.d3");
    let final_task: Value =
        serde_json::from_str(&core.get_item_json("task.al_bar.d3".into()).unwrap()).unwrap();
    assert_eq!(final_task["demand"], "perform");
    assert!(
        final_task["target_text"].is_null(),
        "a perform capstone shows nothing to copy"
    );

    // And the point of all of it.
    let state = cando_state(&core, start + 3 * DAY);
    assert_eq!(
        state["status"], "achieved",
        "after three rising passes and a free performance, the learner can \
         order a coffee — and the app should say so: {state}"
    );
    assert_eq!(state["applied"], true);
}

/// A can-do does not close on the rehearsed pass. Playing only the first
/// framing leaves it in progress, however well the learner does — the
/// scaffolded capstone shows the target, so passing it proves they can
/// read, not that they can order.
#[test]
fn the_scaffolded_capstone_is_not_enough() {
    let Some(core) = open("cando-partial") else {
        eprintln!("MAESTRO_PACK_PATH not set; skipping");
        return;
    };
    let start = 1_754_000_000i64;
    play(&core, 1, start);

    let state = cando_state(&core, start);
    assert_ne!(
        state["status"], "achieved",
        "one rehearsed pass is not evidence of a can-do: {state}"
    );
}
