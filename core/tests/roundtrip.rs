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

        CREATE TABLE media (
            path TEXT PRIMARY KEY, kind TEXT NOT NULL,
            sha256 TEXT NOT NULL, bytes BLOB NOT NULL
        );
        CREATE TABLE tombstones (
            item_id TEXT PRIMARY KEY, removed_in TEXT NOT NULL, reason TEXT
        );
        CREATE TABLE spec_vocab (
            id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL,
            pos TEXT NOT NULL, gloss TEXT NOT NULL
        );

        INSERT INTO spec_grammar VALUES ('pass_pros', 'A2', '[]');
        INSERT INTO spec_scenarios VALUES
            ('in-viaggio', 'A1', 1, NULL, 3, '["pass_pros"]', '[]');
        INSERT INTO spec_vocab VALUES ('mangiare', 'A0', 'verb', 'to eat');

        INSERT INTO manifest VALUES
            ('schema_version', '1'), ('pack_version', '0.0.1-fixture'),
            ('language', 'it');

        INSERT INTO media VALUES (
            'audio/drill.pp_avere_001.wav', 'audio', 'deadbeef', X'52494646'
        );
        INSERT INTO tombstones VALUES
            ('drill.retired_001', '0.0.1-fixture', 'reworked');

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

    // Evidence events round-trip in order and are schema-validated.
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
    assert!(core
        .record_event(r#"{"type":"attempt","outcome":"correct","evidence":[]}"#.into())
        .is_err());
    let events = core.list_events_json().unwrap();
    assert_eq!(events.len(), 3);

    // Derived state reflects the three fresh corrects (mass 3.0 -> mastered).
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;
    let summary: serde_json::Value =
        serde_json::from_str(&core.progress_summary(now).unwrap()).unwrap();
    assert_eq!(summary["grammar"]["pass_pros"]["label"], "consolidated");
    assert_eq!(summary["modality_evidence"]["writing"], 3);

    // Pack status: compatible, and it sees media + tombstones.
    let status = core.pack_status().unwrap();
    assert!(status.compatible);
    assert_eq!(status.schema_version, "1");
    assert_eq!((status.media_count, status.tombstone_count), (1, 1));

    // Media round-trips bytes; a missing path is NotFound.
    let media = core.list_media().unwrap();
    assert_eq!(media[0].path, "audio/drill.pp_avere_001.wav");
    assert_eq!(media[0].size_bytes, 4);
    let blob = core.get_media("audio/drill.pp_avere_001.wav".into()).unwrap();
    assert_eq!(blob.bytes, b"RIFF");
    assert_eq!(blob.kind, "audio");
    assert!(core.get_media("audio/nope.wav".into()).is_err());

    // Tombstones surface for history interpretation.
    let tombs = core.list_tombstones().unwrap();
    assert_eq!(tombs[0].item_id, "drill.retired_001");
    assert_eq!(tombs[0].reason.as_deref(), Some("reworked"));

    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn v0_pack_without_new_tables_still_opens() {
    let dir = std::env::temp_dir().join(format!("maestro-v0-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let pack_path = dir.join("v0.pack.sqlite");
    let _ = std::fs::remove_file(&pack_path);
    let conn = Connection::open(&pack_path).unwrap();
    conn.execute_batch(
        r#"
        CREATE TABLE manifest (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE items (
            id TEXT PRIMARY KEY, item_type TEXT NOT NULL,
            cefr_level TEXT NOT NULL, modality TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        INSERT INTO manifest VALUES
            ('schema_version', '0'), ('pack_version', '0.0.0'), ('language', 'it');
        "#,
    )
    .unwrap();
    drop(conn);

    let learner = dir.join("learner.sqlite");
    let core = Core::open(
        pack_path.to_str().unwrap().into(),
        learner.to_str().unwrap().into(),
    )
    .unwrap();
    let status = core.pack_status().unwrap();
    assert!(status.compatible);
    assert_eq!((status.media_count, status.tombstone_count), (0, 0));
    assert!(core.list_media().unwrap().is_empty());
    assert!(core.list_tombstones().unwrap().is_empty());
    assert!(core.get_media("x".into()).is_err());

    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn future_schema_version_is_refused() {
    let dir = std::env::temp_dir().join(format!("maestro-v9-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let pack_path = dir.join("v9.pack.sqlite");
    let _ = std::fs::remove_file(&pack_path);
    let conn = Connection::open(&pack_path).unwrap();
    conn.execute_batch(
        r#"
        CREATE TABLE manifest (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO manifest VALUES ('schema_version', '9');
        "#,
    )
    .unwrap();
    drop(conn);

    let err = Core::open(
        pack_path.to_str().unwrap().into(),
        dir.join("learner.sqlite").to_str().unwrap().into(),
    )
    .err()
    .expect("open must refuse a future schema");
    assert!(err.to_string().contains("schema_version 9"));

    std::fs::remove_dir_all(&dir).unwrap();
}
