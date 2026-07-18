//! Cross-language contract test: a bundle built by the Python authoring
//! pipeline (`authoring/build_pack.py`) must open and score in the core.
//!
//! Gated on MAESTRO_PACK_PATH so `cargo test` stays hermetic:
//!   python -m authoring.build_pack packs/it build/it.pack.sqlite
//!   MAESTRO_PACK_PATH=../build/it.pack.sqlite cargo test --test pack_compat

use maestro_core::Core;

#[test]
fn opens_and_scores_python_built_pack() {
    let Some(pack_path) = std::env::var_os("MAESTRO_PACK_PATH") else {
        eprintln!("MAESTRO_PACK_PATH not set; skipping pack compat test");
        return;
    };
    let learner = std::env::temp_dir().join(format!("compat-learner-{}.sqlite", std::process::id()));
    let _ = std::fs::remove_file(&learner);

    let core = Core::open(
        pack_path.to_string_lossy().into_owned(),
        learner.to_string_lossy().into_owned(),
    )
    .expect("open python-built pack");

    let manifest = core.manifest().expect("manifest");
    assert_eq!(manifest.language, "it");
    assert!(manifest.item_count > 0);

    // Every item must parse as JSON; every scorable item must score.
    // Reading/listening parents carry the passage + question ids and are
    // not directly scorable — their children are.
    for id in core.list_item_ids().expect("list") {
        let payload = core.get_item_json(id.clone()).expect("payload");
        let parsed: serde_json::Value = serde_json::from_str(&payload).expect("payload JSON");
        assert!(parsed["evidence"].is_array(), "{id}: missing evidence");
        match core.score_attempt(id.clone(), "xyzzy definitely wrong".into()) {
            Ok(miss) => {
                assert!(!miss.correct);
                assert!(!miss.expected.is_empty(), "{id}: no canonical answer");
                let ok = core
                    .score_attempt(id.clone(), miss.expected[0].clone())
                    .expect("score canonical");
                assert!(ok.correct, "{id}: canonical answer not accepted");
            }
            Err(_) => {
                // Only passage parents may lack acceptable answers.
                let qids = parsed["question_ids"].as_array();
                assert!(
                    qids.is_some_and(|q| !q.is_empty()),
                    "{id}: unscorable item without question children"
                );
            }
        }
    }

    // The embedded spec tables must be present and non-trivial.
    let plan = core
        .compose_session(r#"{"now": 1800000000, "seed": 1}"#.into())
        .expect("compose from python-built pack");
    let plan: serde_json::Value = serde_json::from_str(&plan).unwrap();
    assert!(plan["scenario_id"].is_string(), "no scenario chosen: {plan}");

    let _ = std::fs::remove_file(&learner);
}
