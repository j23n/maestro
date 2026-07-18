//! Cross-language contract: core normalization must match the golden
//! vectors that also pin `authoring/build_pack._normalize` (the Python
//! side stores distractor keys pre-normalized, so any divergence makes
//! distractor lookups silently miss).

use serde::Deserialize;

#[derive(Deserialize)]
struct Vectors {
    vectors: Vec<Case>,
}

#[derive(Deserialize)]
struct Case {
    input: String,
    normalized: String,
}

#[test]
fn normalize_matches_shared_vectors() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../conformance/normalize_vectors.json"
    );
    let data: Vectors =
        serde_json::from_str(&std::fs::read_to_string(path).expect("vectors file"))
            .expect("valid vectors json");
    assert!(data.vectors.len() >= 15, "suspiciously few vectors");
    for case in data.vectors {
        assert_eq!(
            maestro_core::normalize::normalize(&case.input),
            case.normalized,
            "input: {:?}",
            case.input
        );
    }
}
