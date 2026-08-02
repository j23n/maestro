//! Simulated-learner test: the composer + folds drive a sane progression
//! over a synthetic pack — prerequisites gate material, mastery rises with
//! correct answers, archetypes shift, repeats are avoided.

use maestro_core::Core;
use rusqlite::Connection;

const NOW: i64 = 1_800_000_000;
const DAY: i64 = 86_400;

/// Synthetic pack: gp_a (A0, no prereqs) -> gp_b (A1, needs gp_a).
/// 6 drills per GP, one reading, one scenario covering both.
fn build_pack(path: &str) {
    let conn = Connection::open(path).unwrap();
    conn.execute_batch(
        r#"
        CREATE TABLE manifest (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE items (
            id TEXT PRIMARY KEY, item_type TEXT NOT NULL,
            cefr_level TEXT NOT NULL, modality TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE acceptable_answers (
            item_id TEXT NOT NULL, answer TEXT NOT NULL,
            is_canonical INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE distractor_feedback (
            item_id TEXT NOT NULL, response_norm TEXT NOT NULL, feedback TEXT NOT NULL
        );
        CREATE TABLE explanations (item_id TEXT PRIMARY KEY, feedback TEXT NOT NULL);
        CREATE TABLE spec_grammar (
            id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL,
            prerequisites TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE spec_functions (id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL);
        CREATE TABLE spec_scenarios (
            id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL,
            phase INTEGER NOT NULL, sequence INTEGER, depth_count INTEGER NOT NULL,
            grammar_ids TEXT NOT NULL DEFAULT '[]',
            function_ids TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE spec_can_dos (
            id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL, skill TEXT NOT NULL,
            grammar_ids TEXT NOT NULL DEFAULT '[]',
            function_ids TEXT NOT NULL DEFAULT '[]'
        );
        INSERT INTO manifest VALUES
            ('schema_version','0'),('pack_version','0.0.1-sim'),('language','it');
        INSERT INTO spec_grammar VALUES ('gp_a','A0','[]');
        INSERT INTO spec_grammar VALUES ('gp_b','A1','["gp_a"]');
        INSERT INTO spec_scenarios VALUES
            ('sc-1','A0',1,1,2,'["gp_a","gp_b"]','[]');
        INSERT INTO spec_can_dos VALUES
            ('a0.demo','A0','spoken_interaction','["gp_a"]','[]');
        "#,
    )
    .unwrap();
    for gp in ["gp_a", "gp_b"] {
        for i in 0..6 {
            let id = format!("drill.{gp}.{i:03}");
            conn.execute(
                "INSERT INTO items VALUES (?1,'drill_cloze', 'A0', 'writing', ?2)",
                rusqlite::params![
                    id,
                    format!(
                        r#"{{"prompt":"p","evidence":[{{"axis":"grammar","id":"{gp}","weight":1.0}}]}}"#
                    )
                ],
            )
            .unwrap();
            conn.execute(
                "INSERT INTO acceptable_answers VALUES (?1,'ok',1)",
                [&id],
            )
            .unwrap();
        }
    }
    conn.execute(
        "INSERT INTO items VALUES ('reading.sc1.001','reading','A0','reading',
         '{\"prompt\":\"r\",\"evidence\":[{\"axis\":\"grammar\",\"id\":\"gp_a\",\"weight\":0.5}]}')",
        [],
    )
    .unwrap();
    conn.execute(
        "INSERT INTO acceptable_answers VALUES ('reading.sc1.001','ok',1)",
        [],
    )
    .unwrap();
}

fn plan(core: &Core, now: i64, seed: u64) -> serde_json::Value {
    serde_json::from_str(
        &core
            .compose_session(format!(r#"{{"now":{now},"seed":{seed}}}"#))
            .unwrap(),
    )
    .unwrap()
}

fn record_correct(core: &Core, item_id: &str, gp: &str, at: i64) {
    core.record_event(format!(
        r#"{{"type":"attempt","at":{at},"item_id":"{item_id}","outcome":"correct",
            "modality":"writing",
            "evidence":[{{"axis":"grammar","id":"{gp}","weight":1.0}}]}}"#
    ))
    .unwrap();
}

/// What the shell emits when a grammar reference page is dismissed.
fn record_introduced(core: &Core, gp: &str, at: i64) {
    core.record_event(format!(
        r#"{{"type":"introduced","at":{at},
            "evidence":[{{"axis":"grammar","id":"{gp}","weight":1.0}}]}}"#
    ))
    .unwrap();
}

#[test]
fn simulated_learner_progresses() {
    let dir = std::env::temp_dir().join(format!("maestro-sim-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let pack = dir.join("sim.pack.sqlite");
    let learner = dir.join("learner.sqlite");
    let _ = std::fs::remove_file(&pack);
    let _ = std::fs::remove_file(&learner);
    build_pack(pack.to_str().unwrap());
    let core = Core::open(
        pack.to_str().unwrap().into(),
        learner.to_str().unwrap().into(),
    )
    .unwrap();

    // Day 0: fresh learner. gp_b is locked (prereq gp_a not introduced), so
    // the first session must target gp_a only, as an introduction.
    let p0 = plan(&core, NOW, 1);
    assert_eq!(p0["archetype"], "introduction");
    assert_eq!(p0["scenario_id"], "sc-1");
    for a in p0["activities"].as_array().unwrap() {
        let id = a["item_id"].as_str().unwrap();
        assert!(
            !id.contains("gp_b"),
            "locked gp_b item {id} appeared in first session"
        );
    }

    // The learner reads gp_a's reference page, then drills it correctly
    // across a few days. The card is what teaches: drilling alone builds
    // mastery without ever introducing the point, so gp_b would stay
    // locked behind a prerequisite the learner had in fact been using.
    record_introduced(&core, "gp_a", NOW);
    for (i, day) in [0i64, 0, 1, 2].iter().enumerate() {
        record_correct(&core, &format!("drill.gp_a.{i:03}"), "gp_a", NOW + day * DAY);
    }

    // gp_a now introduced -> gp_b unlocks; next session should introduce it.
    let p1 = plan(&core, NOW + 3 * DAY, 2);
    assert_eq!(p1["archetype"], "introduction");
    assert!(p1["target_grammar"]
        .as_array()
        .unwrap()
        .iter()
        .any(|g| g == "gp_b"));

    // Play that session: card first, then the drills. Master both GPs and
    // the archetype shifts to application.
    record_introduced(&core, "gp_b", NOW + 4 * DAY);
    for (i, gp) in [(0, "gp_b"), (1, "gp_b"), (2, "gp_b"), (3, "gp_b")] {
        record_correct(&core, &format!("drill.{gp}.{i:03}"), gp, NOW + 4 * DAY);
    }
    let p2 = plan(&core, NOW + 5 * DAY, 3);
    assert_eq!(p2["archetype"], "application", "plan: {p2}");
    // Application sessions include receptive work when available.
    assert!(p2["activities"]
        .as_array()
        .unwrap()
        .iter()
        .any(|a| a["slot"] == "reading" || a["slot"] == "listening"));

    // Anti-repetition: recently-attempted items are avoided while
    // alternatives exist.
    let recent: Vec<String> = (0..4).map(|i| format!("drill.gp_a.{i:03}")).collect();
    let picked: Vec<String> = p2["activities"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a["item_id"].as_str().unwrap().to_string())
        .collect();
    let repeats = picked.iter().filter(|id| recent.contains(id)).count();
    assert!(repeats <= 1, "too many repeats: {picked:?}");

    // Determinism: same seed, same plan.
    let again = plan(&core, NOW + 5 * DAY, 3);
    assert_eq!(p2, again);

    // Progress summary: mastery consolidated, can-do in progress (not
    // achieved — no application-tagged item completed), phase still 1.
    let s: serde_json::Value =
        serde_json::from_str(&core.progress_summary(NOW + 5 * DAY).unwrap()).unwrap();
    assert_eq!(s["grammar"]["gp_a"]["label"], "consolidated");
    assert_eq!(s["can_dos"]["a0.demo"]["status"], "in_progress");
    assert_eq!(s["current_phase"], 1);

    // Scenario completion at depth 1 registers.
    core.record_event(format!(
        r#"{{"type":"scenario_completed","at":{},"scenario_id":"sc-1","depth":1}}"#,
        NOW + 5 * DAY
    ))
    .unwrap();
    let s: serde_json::Value =
        serde_json::from_str(&core.progress_summary(NOW + 6 * DAY).unwrap()).unwrap();
    assert_eq!(s["scenarios"]["sc-1"]["max_depth_completed"], 1);

    std::fs::remove_dir_all(&dir).unwrap();
}
