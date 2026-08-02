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

/// The first lesson a learner ever opens must be *about* its scenario.
/// Grammar tags alone don't achieve that — every `saluti` drill matches
/// every lesson that teaches greetings, and passages and prompts aren't
/// authored per grammar point at all — so items carry `scenario_ids` and
/// the composer ranks on-scenario material first. This asserts against
/// the real bundle, where the off-scenario pool is large enough that a
/// regression would show up immediately.
#[test]
fn first_session_is_about_its_scenario() {
    let Some(pack_path) = std::env::var_os("MAESTRO_PACK_PATH") else {
        eprintln!("MAESTRO_PACK_PATH not set; skipping scenario scoping test");
        return;
    };
    let learner = std::env::temp_dir().join(format!("scoped-learner-{}.sqlite", std::process::id()));
    let _ = std::fs::remove_file(&learner);

    let core = Core::open(
        pack_path.to_string_lossy().into_owned(),
        learner.to_string_lossy().into_owned(),
    )
    .expect("open pack");

    const SCENARIO: &str = "a0-01-in-aereo";

    // What the pack actually offers for this lesson, per item type.
    let mut on_scenario: std::collections::HashMap<String, Vec<String>> = Default::default();
    let mut scenarios_of: std::collections::HashMap<String, Vec<String>> = Default::default();
    for id in core.list_item_ids().expect("list") {
        let payload: serde_json::Value =
            serde_json::from_str(&core.get_item_json(id.clone()).expect("payload")).unwrap();
        let tags: Vec<String> = payload["scenario_ids"]
            .as_array()
            .map(|a| a.iter().filter_map(|t| t.as_str().map(String::from)).collect())
            .unwrap_or_default();
        if tags.iter().any(|t| t == SCENARIO) {
            let item_type = payload["parent_id"]
                .as_str()
                .map_or_else(|| id.split('.').next().unwrap_or_default(), |_| "question");
            on_scenario.entry(item_type.to_string()).or_default().push(id.clone());
        }
        scenarios_of.insert(id, tags);
    }
    assert!(
        on_scenario.contains_key("reading"),
        "fixture assumption broken: {SCENARIO} has no reading to prefer"
    );

    // Several seeds: one lucky draw would have passed before this change.
    for seed in 0..8u64 {
        let plan: serde_json::Value = serde_json::from_str(
            &core
                .compose_session(format!(
                    r#"{{"now": 1800000000, "seed": {seed}, "scenario_id": "{SCENARIO}"}}"#
                ))
                .expect("compose"),
        )
        .unwrap();
        assert_eq!(plan["scenario_id"], SCENARIO);

        let activities = plan["activities"].as_array().expect("activities");
        assert!(!activities.is_empty(), "seed {seed}: empty plan");
        let picked: std::collections::HashSet<&str> = activities
            .iter()
            .map(|a| a["item_id"].as_str().unwrap())
            .collect();

        for a in activities {
            let id = a["item_id"].as_str().unwrap();
            let family = id.split('.').next().unwrap_or_default();
            let tags = &scenarios_of[id];
            // Untagged items are shared material, legal anywhere. A tagged
            // item from another lesson is only acceptable once this
            // lesson's own supply of that kind is exhausted — which is how
            // a lesson with no listening of its own still gets one.
            if tags.is_empty() || tags.iter().any(|t| t == SCENARIO) {
                continue;
            }
            let ours = on_scenario.get(family).map(Vec::as_slice).unwrap_or_default();
            let unused: Vec<&String> = ours.iter().filter(|o| !picked.contains(o.as_str())).collect();
            assert!(
                unused.is_empty(),
                "seed {seed}: {id} ({}) belongs to {tags:?} while {SCENARIO} still has {unused:?}",
                a["slot"]
            );
        }
    }

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
