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
                // Unscorable by design: passage parents (their question
                // children score), reference pages, open writing tasks,
                // and self-graded vocab cards.
                let qids = parsed["question_ids"].as_array();
                let open_family = id.starts_with("grammar_ref.")
                    || id.starts_with("writing.")
                    || id.starts_with("vocab.");
                assert!(
                    open_family || qids.is_some_and(|q| !q.is_empty()),
                    "{id}: unscorable item without question children"
                );
            }
        }
    }

    // Media + tombstones + status must be readable from a python bundle.
    let status = core.pack_status().expect("pack status");
    assert!(status.compatible, "python bundle must be compatible");
    for media in core.list_media().expect("media inventory") {
        let blob = core.get_media(media.path.clone()).expect("media bytes");
        assert_eq!(blob.bytes.len() as u64, media.size_bytes, "{}", media.path);
    }
    core.list_tombstones().expect("tombstones");

    // The embedded spec tables must be present and non-trivial.
    let plan = core
        .compose_session(r#"{"now": 1800000000, "seed": 1}"#.into())
        .expect("compose from python-built pack");
    let plan: serde_json::Value = serde_json::from_str(&plan).unwrap();
    assert!(plan["scenario_id"].is_string(), "no scenario chosen: {plan}");

    let _ = std::fs::remove_file(&learner);
}

/// The vocabulary browser reads `vocab_inventory`. It joins three sources
/// that are built independently — the spec table, the authored cards, and
/// the SM-2 fold — and a lemma mismatch between the first two would show
/// up as a silently unpractisable word rather than as an error.
#[test]
fn vocab_inventory_joins_spec_cards_and_srs() {
    let Some(pack_path) = std::env::var_os("MAESTRO_PACK_PATH") else {
        eprintln!("MAESTRO_PACK_PATH not set; skipping vocab inventory test");
        return;
    };
    let learner = std::env::temp_dir().join(format!("vocab-learner-{}.sqlite", std::process::id()));
    let _ = std::fs::remove_file(&learner);

    let core = Core::open(
        pack_path.to_string_lossy().into_owned(),
        learner.to_string_lossy().into_owned(),
    )
    .expect("open pack");

    const NOW: i64 = 1_800_000_000;
    let read = |core: &Core| -> Vec<serde_json::Value> {
        serde_json::from_str(&core.vocab_inventory(NOW).expect("inventory")).expect("json")
    };

    let entries = read(&core);
    assert!(!entries.is_empty(), "pack has no spec vocabulary");
    for e in &entries {
        assert!(!e["lemma"].as_str().unwrap_or_default().is_empty());
        assert!(!e["gloss"].as_str().unwrap_or_default().is_empty());
        assert_eq!(e["status"], "new", "untouched learner has no SRS state");
    }

    // Every authored card must land on a spec lemma; an orphan would be
    // practisable in a session but invisible in the browser.
    let with_cards: Vec<_> = entries
        .iter()
        .filter(|e| e["item_id"].is_string())
        .collect();
    let card_items = core
        .list_item_ids()
        .expect("list")
        .into_iter()
        .filter(|id| id.starts_with("vocab."))
        .count();
    assert_eq!(
        with_cards.len(),
        card_items,
        "authored vocab cards not all matched to spec lemmas"
    );

    // A review moves that lemma out of "new" and gives it a due date.
    let lemma = with_cards[0]["lemma"].as_str().unwrap().to_string();
    let item_id = with_cards[0]["item_id"].as_str().unwrap().to_string();
    core.record_event(format!(
        r#"{{"type":"attempt","at":{NOW},"item_id":"{item_id}","outcome":"correct",
             "modality":"vocab","evidence_class":"targeted","srs_rating":5,
             "evidence":[{{"axis":"vocab","id":"{lemma}","weight":1.0}}]}}"#
    ))
    .expect("record review");

    let reviewed = read(&core)
        .into_iter()
        .find(|e| e["lemma"] == lemma.as_str())
        .expect("reviewed lemma still listed");
    assert_eq!(reviewed["status"], "learning");
    assert_eq!(reviewed["repetitions"], 1);
    assert_eq!(reviewed["due_in_days"], 1);

    let _ = std::fs::remove_file(&learner);
}
