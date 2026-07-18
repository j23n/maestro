//! Phase 0 walking-skeleton test: build a fixture pack, then exercise the
//! full public surface — open, manifest, fetch, score, record, list.

use maestro_core::Core;
use rusqlite::Connection;

fn build_fixture_pack(path: &str) {
    let conn = Connection::open(path).unwrap();
    conn.execute_batch(
        r#"
        CREATE TABLE manifest (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE items (
            id TEXT PRIMARY KEY, item_type TEXT NOT NULL,
            cefr_level TEXT NOT NULL, modality TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE acceptable_answers (
            item_id TEXT NOT NULL, answer TEXT NOT NULL,
            is_canonical INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE distractor_feedback (
            item_id TEXT NOT NULL, response_norm TEXT NOT NULL,
            feedback TEXT NOT NULL
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

        INSERT INTO spec_grammar VALUES ('pass_pros', 'A2', '[]');
        INSERT INTO spec_scenarios VALUES
            ('in-viaggio', 'A1', 1, NULL, 3, '["pass_pros"]', '[]');

        INSERT INTO manifest VALUES
            ('schema_version', '0'), ('pack_version', '0.0.1-fixture'),
            ('language', 'it');

        INSERT INTO items VALUES (
            'drill.pp_avere_001', 'drill_cloze', 'A2', 'writing',
            '{"prompt": "Ieri ___ (mangiare) la pizza.",
              "evidence": [{"axis": "grammar", "id": "pass_pros", "weight": 1.0}]}'
        );
        INSERT INTO acceptable_answers VALUES
            ('drill.pp_avere_001', 'ho mangiato', 1),
            ('drill.pp_avere_001', 'io ho mangiato', 0);
        INSERT INTO distractor_feedback VALUES (
            'drill.pp_avere_001', 'sono mangiato',
            'mangiare takes avere, not essere: *ho* mangiato.'
        );
        INSERT INTO explanations VALUES (
            'drill.pp_avere_001',
            'Passato prossimo of mangiare: present of avere + mangiato.'
        );
        "#,
    )
    .unwrap();
}

#[test]
fn full_roundtrip() {
    let dir = std::env::temp_dir().join(format!("maestro-fixture-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let pack_path = dir.join("fixture.pack.sqlite");
    let learner_path = dir.join("learner.sqlite");
    let _ = std::fs::remove_file(&pack_path);
    let _ = std::fs::remove_file(&learner_path);
    build_fixture_pack(pack_path.to_str().unwrap());

    let core = Core::open(
        pack_path.to_str().unwrap().into(),
        learner_path.to_str().unwrap().into(),
    )
    .unwrap();

    let manifest = core.manifest().unwrap();
    assert_eq!(manifest.language, "it");
    assert_eq!(manifest.item_count, 1);

    assert_eq!(core.list_item_ids().unwrap(), vec!["drill.pp_avere_001"]);
    let item: serde_json::Value =
        serde_json::from_str(&core.get_item_json("drill.pp_avere_001".into()).unwrap()).unwrap();
    assert!(item["prompt"].as_str().unwrap().contains("mangiare"));

    // Correct, with normalization tolerance (case, punctuation, whitespace).
    let ok = core
        .score_attempt("drill.pp_avere_001".into(), "  Ho  mangiato! ".into())
        .unwrap();
    assert!(ok.correct);
    assert_eq!(ok.matched_answer.as_deref(), Some("ho mangiato"));

    // Non-canonical acceptable variant still counts.
    assert!(core
        .score_attempt("drill.pp_avere_001".into(), "io ho mangiato".into())
        .unwrap()
        .correct);

    // Anticipated wrong answer gets its curated feedback.
    let miss = core
        .score_attempt("drill.pp_avere_001".into(), "sono mangiato".into())
        .unwrap();
    assert!(!miss.correct);
    assert_eq!(miss.expected, vec!["ho mangiato"]);
    assert!(miss.feedback.unwrap().contains("avere"));

    // Unanticipated wrong answer falls back to the general explanation.
    let other = core
        .score_attempt("drill.pp_avere_001".into(), "mangiavo".into())
        .unwrap();
    assert!(other.feedback.unwrap().contains("Passato prossimo"));

    // Evidence events round-trip in order.
    let attempt = |outcome: &str| {
        format!(
            r#"{{"type":"attempt","item_id":"drill.pp_avere_001","outcome":"{outcome}",
                "modality":"writing",
                "evidence":[{{"axis":"grammar","id":"pass_pros","weight":1.0}}]}}"#
        )
    };
    core.record_event(attempt("correct")).unwrap();
    core.record_event(attempt("correct")).unwrap();
    core.record_event(attempt("correct")).unwrap();
    assert!(core.record_event("not json".into()).is_err());
    let events = core.list_events_json().unwrap();
    assert_eq!(events.len(), 3);

    std::fs::remove_dir_all(&dir).unwrap();
}
