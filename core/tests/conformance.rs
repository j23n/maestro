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
        if vector.get("spec").is_none_or(Value::is_null) {
            // Not a fold vector (e.g. normalize_vectors.json, which has
            // its own dedicated runner in tests/normalize_parity.rs).
            continue;
        }
        let name = vector["name"].as_str().unwrap_or("unnamed");
        let ctx = format!("{}: {name}", path.file_name().unwrap().to_string_lossy());

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
            if let Some(v) = expect.get("current_phase") {
                assert_eq!(state.current_phase as i64, v.as_i64().unwrap(), "{ctx}: phase");
            }
            if let Some(grammar) = expect.get("grammar").and_then(|g| g.as_object()) {
                for (gp, exp) in grammar {
                    let actual = state
                        .grammar
                        .get(gp)
                        .unwrap_or_else(|| panic!("{ctx}: no grammar state for {gp}"));
                    if let Some(label) = exp["label"].as_str() {
                        assert_eq!(actual.label, label, "{ctx}: {gp} label");
                    }
                    if let Some(m) = exp["mastery_approx"].as_f64() {
                        let tol = exp["tolerance"].as_f64().unwrap_or(1e-6);
                        approx(actual.mastery.expect("mastery"), m, tol, &format!("{ctx}: {gp}"));
                    }
                }
            }
            if let Some(vocab) = expect.get("vocab").and_then(|v| v.as_object()) {
                for (lemma, exp) in vocab {
                    let card = state
                        .vocab
                        .get(lemma)
                        .unwrap_or_else(|| panic!("{ctx}: no card for {lemma}"));
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
    assert!(ran >= 3, "expected at least 3 vectors, ran {ran}");
}
