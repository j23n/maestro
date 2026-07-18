//! Emit a tiny fixture pack bundle for shell development:
//! `cargo run --example make_fixture -- /path/to/fixture.pack.sqlite`
//!
//! Same content as tests/roundtrip.rs — one passato prossimo cloze drill
//! with acceptable answers, distractor feedback, and an explanation.

use rusqlite::Connection;

fn main() {
    let path = std::env::args()
        .nth(1)
        .expect("usage: make_fixture <output-path>");
    let _ = std::fs::remove_file(&path);
    let conn = Connection::open(&path).expect("create fixture db");
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
    .expect("populate fixture");
    println!("wrote {path}");
}
