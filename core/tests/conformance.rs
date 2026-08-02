//! Run every golden vector in ../conformance/ against the fold + composer.
//! See conformance/README.md for the vector format and the rules for
//! changing expectations.

use maestro_core::folds::{fold, unlocked_grammar};
use maestro_core::model::EvidenceEvent;
use maestro_core::pack::SpecData;
use serde_json::Value;

fn approx(actual: f64, expected: f64, tolerance: f64, ctx: &str) {
    assert!(
        (actual - expected).abs() <= tolerance,
        "{ctx}: {actual} !~ {expected} (tol {tolerance})"
    );
}

#[test]
fn golden_vectors() {
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../conformance");
    let mut ran = 0;
    let mut paths: Vec<_> = std::fs::read_dir(&dir)
        .expect("conformance dir")
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|e| e == "json"))
        .collect();
    paths.sort();

    for path in paths {
        let raw = std::fs::read_to_string(&path).unwrap();
        let vector: Value = serde_json::from_str(&raw).unwrap();
        let name = vector["name"].as_str().unwrap_or("unnamed");
        let ctx = format!("{}: {name}", path.file_name().unwrap().to_string_lossy());

        if let Some(cases) = vector.get("alignment_cases").and_then(Value::as_array) {
            run_alignment_cases(&ctx, cases);
            ran += 1;
            continue;
        }
        if let Some(cases) = vector.get("scoring_cases").and_then(Value::as_array) {
            run_scoring_cases(&ctx, cases);
            ran += 1;
            continue;
        }
        if vector.get("session_options").is_some() {
            run_session_vector(&ctx, &vector);
            ran += 1;
            continue;
        }
        if vector.get("spec").is_none_or(Value::is_null) {
            // Not a fold vector (e.g. normalize_vectors.json, which has
            // its own dedicated runner in tests/normalize_parity.rs).
            continue;
        }

        let spec: SpecData = serde_json::from_value(vector["spec"].clone()).unwrap();
        let events: Vec<EvidenceEvent> =
            serde_json::from_value(vector["events"].clone()).unwrap();
        for (i, ev) in events.iter().enumerate() {
            ev.validate().unwrap_or_else(|e| panic!("{ctx}: event {i}: {e}"));
            assert!(ev.at.is_some(), "{ctx}: event {i} must carry explicit `at`");
        }
        let now = vector["now"].as_i64().expect("now");
        let state = fold(&events, &spec, now);

        if let Some(expect) = vector["expect_state"].as_object() {
            if let Some(v) = expect.get("cefr_estimate") {
                assert_eq!(&state.cefr_estimate, v.as_str().unwrap(), "{ctx}: cefr");
            }
            if let Some(cefr) = expect.get("cefr").and_then(|c| c.as_object()) {
                let actual = serde_json::to_value(&state.cefr).unwrap();
                for (field, want) in cefr {
                    assert_eq!(
                        actual.get(field),
                        Some(want),
                        "{ctx}: cefr.{field} (full: {actual})"
                    );
                }
            }
            if let Some(v) = expect.get("current_phase") {
                assert_eq!(state.current_phase as i64, v.as_i64().unwrap(), "{ctx}: phase");
            }
            if let Some(grammar) = expect.get("grammar").and_then(|g| g.as_object()) {
                for (gp, exp) in grammar {
                    if exp["absent"].as_bool() == Some(true) {
                        assert!(
                            !state.grammar.contains_key(gp),
                            "{ctx}: {gp} should have no grammar state"
                        );
                        continue;
                    }
                    let actual = state
                        .grammar
                        .get(gp)
                        .unwrap_or_else(|| panic!("{ctx}: no grammar state for {gp}"));
                    if let Some(label) = exp["label"].as_str() {
                        assert_eq!(actual.label, label, "{ctx}: {gp} label");
                    }
                    if let Some(want) = exp["introduced"].as_bool() {
                        assert_eq!(actual.introduced, want, "{ctx}: {gp} introduced");
                    }
                    if let Some(m) = exp["mastery_approx"].as_f64() {
                        let tol = exp["tolerance"].as_f64().unwrap_or(1e-6);
                        approx(actual.mastery.expect("mastery"), m, tol, &format!("{ctx}: {gp}"));
                    }
                }
            }
            if let Some(vocab) = expect.get("vocab").and_then(|v| v.as_object()) {
                for (lemma, exp) in vocab {
                    if exp["absent"].as_bool() == Some(true) {
                        assert!(
                            !state.vocab.contains_key(lemma),
                            "{ctx}: {lemma} should not be in the learner's vocabulary"
                        );
                        continue;
                    }
                    let card = state
                        .vocab
                        .get(lemma)
                        .unwrap_or_else(|| panic!("{ctx}: no card for {lemma}"));
                    if let Some(r) = exp["reviews"].as_u64() {
                        assert_eq!(card.reviews as u64, r, "{ctx}: {lemma} reviews");
                    }
                    if let Some(d) = exp["due_in_days"].as_i64() {
                        let now = vector["now"].as_i64().expect("vector needs `now`");
                        assert_eq!(
                            card.due_day - maestro_core::model::unix_day(now),
                            d,
                            "{ctx}: {lemma} due offset"
                        );
                    }
                    if let Some(r) = exp["repetitions"].as_u64() {
                        assert_eq!(card.repetitions as u64, r, "{ctx}: {lemma} reps");
                    }
                    if let Some(i) = exp["interval_days"].as_u64() {
                        assert_eq!(card.interval_days as u64, i, "{ctx}: {lemma} interval");
                    }
                    if let Some(e) = exp["ease_factor_approx"].as_f64() {
                        let tol = exp["tolerance"].as_f64().unwrap_or(1e-6);
                        approx(card.ease_factor, e, tol, &format!("{ctx}: {lemma} ease"));
                    }
                }
            }
        }
        if let Some(expected_unlocked) = vector["expect_unlocked"].as_array() {
            let mut unlocked = unlocked_grammar(&state, &spec);
            unlocked.sort();
            let mut expected: Vec<String> = expected_unlocked
                .iter()
                .map(|v| v.as_str().unwrap().to_string())
                .collect();
            expected.sort();
            assert_eq!(unlocked, expected, "{ctx}: unlocked");
        }
        ran += 1;
    }
    assert!(ran >= 6, "expected at least 6 vectors, ran {ran}");
}

// --------------------------------------------------------------------------
// Alignment vectors: pin the speaking scorer word by word.

fn run_alignment_cases(ctx: &str, cases: &[Value]) {
    for (i, case) in cases.iter().enumerate() {
        let cctx = format!("{ctx}: case {i}");
        let result = maestro_core::align::align_transcript(
            case["target"].as_str().unwrap().to_string(),
            case["transcript"].as_str().unwrap().to_string(),
        );
        let actual = serde_json::to_value(&result).unwrap();
        let expect = &case["expect"];
        if let Some(score) = expect["score"].as_f64() {
            approx(result.score, score, 1e-6, &format!("{cctx}: score"));
        }
        if let Some(statuses) = expect["statuses"].as_array() {
            let actual_statuses: Vec<&str> = actual["verdicts"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v["status"].as_str().unwrap())
                .collect();
            let expected: Vec<&str> = statuses.iter().map(|s| s.as_str().unwrap()).collect();
            assert_eq!(actual_statuses, expected, "{cctx}: statuses");
        }
        if let Some(extra) = expect["extra_words"].as_array() {
            let expected: Vec<&str> = extra.iter().map(|s| s.as_str().unwrap()).collect();
            assert_eq!(result.extra_words, expected, "{cctx}: extra words");
        }
    }
}

// --------------------------------------------------------------------------
// Scoring vectors: pin answer matching + distractor feedback lookup over
// a per-case in-memory bundle.

fn run_scoring_cases(ctx: &str, cases: &[Value]) {
    for (i, case) in cases.iter().enumerate() {
        let cctx = format!("{ctx}: case {i}");
        let conn = rusqlite::Connection::open_in_memory().unwrap();
        conn.execute_batch(
            "CREATE TABLE acceptable_answers (
                 item_id TEXT, answer TEXT, is_canonical INTEGER DEFAULT 0);
             CREATE TABLE distractor_feedback (
                 item_id TEXT, response_norm TEXT, feedback TEXT);
             CREATE TABLE explanations (item_id TEXT PRIMARY KEY, feedback TEXT);",
        )
        .unwrap();
        for a in case["answers"].as_array().unwrap() {
            conn.execute(
                "INSERT INTO acceptable_answers VALUES ('item', ?1, ?2)",
                rusqlite::params![
                    a["text"].as_str().unwrap(),
                    a["canonical"].as_bool().unwrap_or(false)
                ],
            )
            .unwrap();
        }
        if let Some(distractors) = case["distractors"].as_object() {
            for (resp_norm, feedback) in distractors {
                conn.execute(
                    "INSERT INTO distractor_feedback VALUES ('item', ?1, ?2)",
                    rusqlite::params![resp_norm, feedback.as_str().unwrap()],
                )
                .unwrap();
            }
        }
        if let Some(explanation) = case["explanation"].as_str() {
            conn.execute(
                "INSERT INTO explanations VALUES ('item', ?1)",
                [explanation],
            )
            .unwrap();
        }

        let result = maestro_core::pack::score_attempt(
            &conn,
            "item",
            case["response"].as_str().unwrap(),
        )
        .unwrap();
        let expect = &case["expect"];
        assert_eq!(
            result.correct,
            expect["correct"].as_bool().unwrap(),
            "{cctx}: correct"
        );
        if let Some(matched) = expect.get("matched_answer") {
            assert_eq!(
                result.matched_answer.as_deref(),
                matched.as_str(),
                "{cctx}: matched_answer"
            );
        }
        if let Some(feedback) = expect.get("feedback") {
            assert_eq!(result.feedback.as_deref(), feedback.as_str(), "{cctx}: feedback");
        }
    }
}

// --------------------------------------------------------------------------
// Session vectors: pin the composer end to end — scenario choice,
// archetype, and the exact ordered activity list for a fixed seed.

fn run_session_vector(ctx: &str, vector: &Value) {
    let spec: SpecData = serde_json::from_value(vector["spec"].clone()).unwrap();
    let events: Vec<EvidenceEvent> = serde_json::from_value(vector["events"].clone()).unwrap();
    for (i, ev) in events.iter().enumerate() {
        ev.validate().unwrap_or_else(|e| panic!("{ctx}: event {i}: {e}"));
        assert!(ev.at.is_some(), "{ctx}: event {i} must carry explicit `at`");
    }
    let opts: maestro_core::model::SessionOptions =
        serde_json::from_value(vector["session_options"].clone()).unwrap();
    let items: Vec<maestro_core::pack::ItemMeta> = vector["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| maestro_core::pack::ItemMeta {
            id: v["id"].as_str().unwrap().to_string(),
            item_type: v["item_type"].as_str().unwrap().to_string(),
            cefr_level: v["cefr_level"].as_str().unwrap_or("A0").to_string(),
            modality: v["modality"].as_str().unwrap_or("writing").to_string(),
            grammar_ids: str_vec(&v["grammar_ids"]),
            cando_ids: str_vec(&v["cando_ids"]),
            vocab_ids: str_vec(&v["vocab_ids"]),
            scenario_ids: str_vec(&v["scenario_ids"]),
            // Optional in vectors: the ones written before the demand
            // ladder describe selection that doesn't depend on it.
            demand: serde_json::from_value(v["demand"].clone()).unwrap_or(None),
        })
        .collect();

    let state = fold(&events, &spec, opts.now);
    let plan = maestro_core::session::compose(&items, &spec, &state, &opts);
    let actual = serde_json::to_value(&plan).unwrap();

    let expect = &vector["expect_plan"];
    assert!(
        expect.is_object() && !expect.as_object().unwrap().is_empty(),
        "{ctx}: expect_plan missing — actual plan was: {actual}"
    );
    if let Some(scenario) = expect.get("scenario_id") {
        assert_eq!(&actual["scenario_id"], scenario, "{ctx}: scenario_id");
    }
    if let Some(archetype) = expect.get("archetype") {
        assert_eq!(&actual["archetype"], archetype, "{ctx}: archetype");
    }
    if let Some(activities) = expect.get("activities").and_then(Value::as_array) {
        let actual_acts: Vec<(String, String)> = actual["activities"]
            .as_array()
            .unwrap()
            .iter()
            .map(|a| {
                (
                    a["item_id"].as_str().unwrap().to_string(),
                    a["slot"].as_str().unwrap().to_string(),
                )
            })
            .collect();
        let expected_acts: Vec<(String, String)> = activities
            .iter()
            .map(|a| {
                (
                    a["item_id"].as_str().unwrap().to_string(),
                    a["slot"].as_str().unwrap().to_string(),
                )
            })
            .collect();
        assert_eq!(
            actual_acts, expected_acts,
            "{ctx}: activities (actual plan: {actual})"
        );
    }
    if let Some(shortfalls) = expect.get("shortfalls").and_then(Value::as_array) {
        let triples = |v: &Value| -> Vec<(String, u64, u64)> {
            v.as_array()
                .unwrap_or(&vec![])
                .iter()
                .map(|s| {
                    (
                        s["slot"].as_str().unwrap().to_string(),
                        s["requested"].as_u64().unwrap(),
                        s["filled"].as_u64().unwrap(),
                    )
                })
                .collect()
        };
        assert_eq!(
            triples(&actual["shortfalls"]),
            triples(&Value::Array(shortfalls.clone())),
            "{ctx}: shortfalls (actual plan: {actual})"
        );
    }
}

fn str_vec(v: &Value) -> Vec<String> {
    v.as_array()
        .map(|a| {
            a.iter()
                .map(|s| s.as_str().unwrap().to_string())
                .collect()
        })
        .unwrap_or_default()
}
