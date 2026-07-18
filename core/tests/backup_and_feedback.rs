//! Stage 5 contracts: export/import backup, and the pending-feedback
//! queue with evidence fold-back.

use maestro_core::Core;
use rusqlite::Connection;

fn minimal_pack(path: &str) {
    let conn = Connection::open(path).unwrap();
    conn.execute_batch(
        r#"
        CREATE TABLE manifest (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE items (
            id TEXT PRIMARY KEY, item_type TEXT NOT NULL,
            cefr_level TEXT NOT NULL, modality TEXT NOT NULL,
            payload TEXT NOT NULL
        );
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
        INSERT INTO spec_grammar VALUES ('ind_pres', 'A1', '[]');
        INSERT INTO manifest VALUES
            ('schema_version', '0'), ('pack_version', '0.0.1'), ('language', 'it');
        "#,
    )
    .unwrap();
}

fn setup(tag: &str) -> (std::path::PathBuf, std::sync::Arc<Core>) {
    let dir = std::env::temp_dir().join(format!("maestro-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let pack = dir.join("pack.sqlite");
    minimal_pack(pack.to_str().unwrap());
    let core = Core::open(
        pack.to_str().unwrap().into(),
        dir.join("learner.sqlite").to_str().unwrap().into(),
    )
    .unwrap();
    (dir, core)
}

const ATTEMPT: &str = r#"{"type":"attempt","item_id":"drill.x","outcome":"correct",
    "modality":"writing","at":1700000000,
    "evidence":[{"axis":"grammar","id":"ind_pres","weight":1.0}]}"#;

#[test]
fn export_then_import_restores_identical_state() {
    let (dir, core) = setup("backup");
    core.record_event(ATTEMPT.into()).unwrap();
    core.record_event(ATTEMPT.replace("correct", "incorrect")).unwrap();
    core.record_event(ATTEMPT.into()).unwrap();

    let exported = core.export_log().unwrap();
    assert!(exported.starts_with(r#"{"maestro_export":1}"#));
    assert_eq!(exported.trim_end().lines().count(), 4); // header + 3 events

    // Restore on a "second device".
    let pack2 = dir.join("pack2.sqlite");
    minimal_pack(pack2.to_str().unwrap());
    let core2 = Core::open(
        pack2.to_str().unwrap().into(),
        dir.join("learner2.sqlite").to_str().unwrap().into(),
    )
    .unwrap();
    assert_eq!(core2.import_log(exported.clone()).unwrap(), 3);

    let now = 1700000001;
    assert_eq!(
        core.progress_summary(now).unwrap(),
        core2.progress_summary(now).unwrap(),
        "derived state must be identical after restore"
    );

    // Restore never merges into existing history.
    assert!(core2.import_log(exported).is_err());

    // Garbage is rejected before anything is written.
    let core3 = Core::open(
        pack2.to_str().unwrap().into(),
        dir.join("learner3.sqlite").to_str().unwrap().into(),
    )
    .unwrap();
    assert!(core3.import_log("junk".into()).is_err());
    assert!(core3
        .import_log(format!(
            "{}\n{}",
            r#"{"maestro_export":1}"#,
            r#"{"created_at":1,"payload":{"type":"attempt"}}"#
        ))
        .is_err());
    assert_eq!(core3.list_events_json().unwrap().len(), 0);

    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn feedback_queue_lifecycle_folds_evidence_back() {
    let (dir, core) = setup("feedback");

    // Enqueue while "offline".
    let req = serde_json::json!({
        "kind": "writing_feedback",
        "item_id": "writing.a0_presentarsi.001",
        "submission": "Mi chiamo Anna e sono di Milano.",
        "context": {"weakness_tags": ["essere_pre"]}
    });
    let job_id = core.enqueue_feedback_job(req.to_string()).unwrap();
    assert!(job_id > 0);

    // Bad requests are refused.
    assert!(core
        .enqueue_feedback_job(r#"{"kind":"nope","item_id":"x","submission":"y"}"#.into())
        .is_err());

    let pending = core.list_pending_feedback_jobs().unwrap();
    assert_eq!(pending.len(), 1);
    let job: serde_json::Value = serde_json::from_str(&pending[0]).unwrap();
    assert_eq!(job["id"].as_i64(), Some(job_id));
    assert_eq!(job["request"]["kind"], "writing_feedback");

    // A backend appears and completes the job with graded evidence.
    let result = serde_json::json!({
        "feedback_text": "Ottimo inizio! Watch the preposition: «di Milano» is right.",
        "evidence_event": {
            "type": "attempt",
            "item_id": "writing.a0_presentarsi.001",
            "outcome": "correct",
            "modality": "writing",
            "evidence_class": "productive",
            "at": 1700000100,
            "evidence": [{"axis": "grammar", "id": "ind_pres", "weight": 1.0}]
        }
    });
    core.complete_feedback_job(job_id, "anthropic".into(), result.to_string())
        .unwrap();

    // Queue drained; double completion refused.
    assert!(core.list_pending_feedback_jobs().unwrap().is_empty());
    assert!(core
        .complete_feedback_job(job_id, "anthropic".into(), result.to_string())
        .is_err());

    // The evidence event landed, stamped with the backend as source.
    let events = core.list_events_json().unwrap();
    assert_eq!(events.len(), 1);
    let ev: serde_json::Value = serde_json::from_str(&events[0]).unwrap();
    assert_eq!(ev["feedback_source"], "anthropic");
    assert_eq!(ev["outcome"], "correct");

    std::fs::remove_dir_all(&dir).unwrap();
}
