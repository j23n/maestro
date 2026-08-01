//! Read-only access to a content pack bundle (one SQLite file).
//!
//! Bundle schema (written by `authoring/build_pack.py` — that file and
//! this one are the two ends of the contract):
//!
//! ```sql
//! CREATE TABLE manifest (key TEXT PRIMARY KEY, value TEXT NOT NULL);
//! CREATE TABLE items (
//!     id         TEXT PRIMARY KEY,   -- stable forever
//!     item_type  TEXT NOT NULL,      -- drill_cloze, reading, vocab_card, ...
//!     cefr_level TEXT NOT NULL,
//!     modality   TEXT NOT NULL,      -- reading/listening/writing/speaking/vocab
//!     payload    TEXT NOT NULL       -- JSON, shape depends on item_type
//! );
//! CREATE TABLE acceptable_answers (
//!     item_id      TEXT NOT NULL REFERENCES items(id),
//!     answer       TEXT NOT NULL,    -- stored as authored
//!     is_canonical INTEGER NOT NULL DEFAULT 0
//! );
//! CREATE TABLE distractor_feedback (
//!     item_id       TEXT NOT NULL REFERENCES items(id),
//!     response_norm TEXT NOT NULL,   -- normalized anticipated wrong answer
//!     feedback      TEXT NOT NULL
//! );
//! CREATE TABLE explanations (
//!     item_id  TEXT PRIMARY KEY REFERENCES items(id),
//!     feedback TEXT NOT NULL         -- general mistake explanation
//! );
//! The spec tables carry a trailing `label` column (grammar, functions,
//! can-dos) holding the learner-facing name. It is deliberately NOT a
//! schema_version bump: the columns have defaults and sit at the end, so
//! an older core reading a newer bundle simply doesn't select them, and a
//! newer core reading an older bundle falls back to the id via
//! `column_exists`. Bumping would make already-shipped apps reject a pack
//! over an additive change.
//!
//! -- schema_version >= 1:
//! CREATE TABLE media (
//!     path   TEXT PRIMARY KEY,       -- as referenced by item payloads
//!     kind   TEXT NOT NULL,          -- audio | image
//!     sha256 TEXT NOT NULL,
//!     bytes  BLOB NOT NULL
//! );
//! CREATE TABLE tombstones (
//!     item_id    TEXT PRIMARY KEY,   -- removed item, id never reused
//!     removed_in TEXT NOT NULL,      -- first pack_version without it
//!     reason     TEXT
//! );
//! CREATE TABLE spec_vocab (
//!     id TEXT PRIMARY KEY, cefr_level TEXT NOT NULL,
//!     pos TEXT NOT NULL, gloss TEXT NOT NULL
//! );
//! ```
//!
//! Scenario art is convention-addressed: `images/scenarios/<id>.png` in
//! the media table, no spec column.

use rusqlite::{Connection, OpenFlags, OptionalExtension};
use serde::Deserialize;

use crate::normalize::normalize;
use crate::{CoreError, MediaBlob, MediaInfo, PackManifest, PackStatus, ScoreResult, TombstoneRecord};

/// Bundle schema versions this core knows how to read. Opening anything
/// else fails fast — the app should prompt for an update instead of
/// misreading a newer bundle.
pub const SUPPORTED_SCHEMA_VERSIONS: &[&str] = &["0", "1"];

// --------------------------------------------------------------------------
// Curriculum spec tables, embedded in the bundle by `authoring/build_pack.py`
// so the composer has the DAG and decompositions offline.

#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct SpecGrammar {
    pub id: String,
    pub cefr_level: String,
    pub prerequisites: Vec<String>,
    /// Human-readable name, for anything the learner sees. Empty on
    /// pre-label bundles — fall back to the id.
    pub label: String,
}

#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct SpecFunction {
    pub id: String,
    pub cefr_level: String,
    pub label: String,
}

#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct SpecScenario {
    pub id: String,
    pub cefr_level: String,
    pub phase: u32,
    pub sequence: Option<u32>,
    pub depth_count: u8,
    pub grammar_ids: Vec<String>,
    pub function_ids: Vec<String>,
}

#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct SpecCanDo {
    pub id: String,
    pub cefr_level: String,
    pub skill: String,
    pub grammar_ids: Vec<String>,
    pub function_ids: Vec<String>,
    /// The can-do statement itself ("Can greet people, say goodbye…").
    pub label: String,
}

#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct SpecVocab {
    pub id: String,
    pub cefr_level: String,
    pub pos: String,
    pub gloss: String,
}

#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct SpecData {
    pub grammar: Vec<SpecGrammar>,
    pub functions: Vec<SpecFunction>,
    pub scenarios: Vec<SpecScenario>,
    pub can_dos: Vec<SpecCanDo>,
    pub vocab: Vec<SpecVocab>,
}

/// Item metadata the session composer selects on (payload stays lazy).
#[derive(Debug, Clone)]
pub struct ItemMeta {
    pub id: String,
    pub item_type: String,
    pub cefr_level: String,
    pub modality: String,
    pub grammar_ids: Vec<String>,
    pub cando_ids: Vec<String>,
    /// Spec lemma ids (vocab-axis evidence) — the SRS scheduler's key.
    pub vocab_ids: Vec<String>,
}

#[derive(Deserialize)]
struct PayloadEvidence {
    #[serde(default)]
    evidence: Vec<PayloadEvidenceRef>,
}

#[derive(Deserialize)]
struct PayloadEvidenceRef {
    axis: String,
    id: String,
}

fn json_vec(s: &str) -> Vec<String> {
    serde_json::from_str(s).unwrap_or_default()
}

pub fn load_spec(conn: &Connection) -> Result<SpecData, CoreError> {
    let mut spec = SpecData::default();
    // `label` arrived with schema_version 2; older bundles don't have the
    // column, so select it only when it exists and fall back to "".
    let gp_label = column_exists(conn, "spec_grammar", "label")?;
    let mut stmt = conn.prepare(if gp_label {
        "SELECT id, cefr_level, prerequisites, label FROM spec_grammar"
    } else {
        "SELECT id, cefr_level, prerequisites, '' FROM spec_grammar"
    })?;
    spec.grammar = stmt
        .query_map([], |r| {
            Ok(SpecGrammar {
                id: r.get(0)?,
                cefr_level: r.get(1)?,
                prerequisites: json_vec(&r.get::<_, String>(2)?),
                label: r.get(3)?,
            })
        })?
        .collect::<Result<_, _>>()?;
    let cf_label = column_exists(conn, "spec_functions", "label")?;
    let mut stmt = conn.prepare(if cf_label {
        "SELECT id, cefr_level, label FROM spec_functions"
    } else {
        "SELECT id, cefr_level, '' FROM spec_functions"
    })?;
    spec.functions = stmt
        .query_map([], |r| {
            Ok(SpecFunction {
                id: r.get(0)?,
                cefr_level: r.get(1)?,
                label: r.get(2)?,
            })
        })?
        .collect::<Result<_, _>>()?;
    let mut stmt = conn.prepare(
        "SELECT id, cefr_level, phase, sequence, depth_count, grammar_ids, function_ids
         FROM spec_scenarios ORDER BY phase, COALESCE(sequence, 999), id",
    )?;
    spec.scenarios = stmt
        .query_map([], |r| {
            Ok(SpecScenario {
                id: r.get(0)?,
                cefr_level: r.get(1)?,
                phase: r.get(2)?,
                sequence: r.get(3)?,
                depth_count: r.get(4)?,
                grammar_ids: json_vec(&r.get::<_, String>(5)?),
                function_ids: json_vec(&r.get::<_, String>(6)?),
            })
        })?
        .collect::<Result<_, _>>()?;
    let cd_label = column_exists(conn, "spec_can_dos", "label")?;
    let mut stmt = conn.prepare(if cd_label {
        "SELECT id, cefr_level, skill, grammar_ids, function_ids, label FROM spec_can_dos"
    } else {
        "SELECT id, cefr_level, skill, grammar_ids, function_ids, '' FROM spec_can_dos"
    })?;
    spec.can_dos = stmt
        .query_map([], |r| {
            Ok(SpecCanDo {
                id: r.get(0)?,
                cefr_level: r.get(1)?,
                skill: r.get(2)?,
                grammar_ids: json_vec(&r.get::<_, String>(3)?),
                function_ids: json_vec(&r.get::<_, String>(4)?),
                label: r.get(5)?,
            })
        })?
        .collect::<Result<_, _>>()?;
    // schema_version >= 1 only; older bundles just have no vocab data.
    if table_exists(conn, "spec_vocab")? {
        let mut stmt = conn.prepare("SELECT id, cefr_level, pos, gloss FROM spec_vocab")?;
        spec.vocab = stmt
            .query_map([], |r| {
                Ok(SpecVocab {
                    id: r.get(0)?,
                    cefr_level: r.get(1)?,
                    pos: r.get(2)?,
                    gloss: r.get(3)?,
                })
            })?
            .collect::<Result<_, _>>()?;
    }
    Ok(spec)
}

pub fn list_item_meta(conn: &Connection) -> Result<Vec<ItemMeta>, CoreError> {
    let mut stmt =
        conn.prepare("SELECT id, item_type, cefr_level, modality, payload FROM items ORDER BY id")?;
    let metas = stmt
        .query_map([], |r| {
            let payload: String = r.get(4)?;
            let ev: PayloadEvidence = serde_json::from_str(&payload).unwrap_or(PayloadEvidence {
                evidence: vec![],
            });
            Ok(ItemMeta {
                id: r.get(0)?,
                item_type: r.get(1)?,
                cefr_level: r.get(2)?,
                modality: r.get(3)?,
                grammar_ids: ev
                    .evidence
                    .iter()
                    .filter(|e| e.axis == "grammar")
                    .map(|e| e.id.clone())
                    .collect(),
                cando_ids: ev
                    .evidence
                    .iter()
                    .filter(|e| e.axis == "cando")
                    .map(|e| e.id.clone())
                    .collect(),
                vocab_ids: ev
                    .evidence
                    .iter()
                    .filter(|e| e.axis == "vocab")
                    .map(|e| e.id.clone())
                    .collect(),
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(metas)
}

pub fn open_readonly(path: &str) -> Result<Connection, CoreError> {
    let conn = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    // Fail fast if this isn't a pack bundle.
    conn.query_row("SELECT count(*) FROM manifest", [], |_| Ok(()))
        .map_err(|_| CoreError::Invalid {
            message: format!("{path} is not a Maestro pack bundle"),
        })?;
    // ... or one from a future schema this core can't interpret.
    let schema_version: String = conn
        .query_row(
            "SELECT value FROM manifest WHERE key = 'schema_version'",
            [],
            |row| row.get(0),
        )
        .optional()?
        .unwrap_or_default();
    if !SUPPORTED_SCHEMA_VERSIONS.contains(&schema_version.as_str()) {
        return Err(CoreError::Invalid {
            message: format!(
                "pack schema_version {schema_version} is newer than this app \
                 supports ({SUPPORTED_SCHEMA_VERSIONS:?}) — update the app"
            ),
        });
    }
    Ok(conn)
}

/// Whether a table carries a column. Lets the reader accept bundles built
/// before a column was added, instead of hard-failing on schema drift.
fn column_exists(conn: &Connection, table: &str, column: &str) -> Result<bool, CoreError> {
    let mut stmt = conn.prepare(&format!("PRAGMA table_info({table})"))?;
    let mut rows = stmt.query([])?;
    while let Some(row) = rows.next()? {
        if row.get::<_, String>(1)? == column {
            return Ok(true);
        }
    }
    Ok(false)
}

fn table_exists(conn: &Connection, name: &str) -> Result<bool, CoreError> {
    let n: u32 = conn.query_row(
        "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = ?1",
        [name],
        |row| row.get(0),
    )?;
    Ok(n > 0)
}

/// Everything the shell needs for the pack-manager screen: identity,
/// compatibility, and what the bundle carries. Unlike `read_manifest`,
/// this can't fail on a healthy bundle of any supported version.
pub fn pack_status(conn: &Connection) -> Result<PackStatus, CoreError> {
    let manifest = read_manifest(conn)?;
    let media_count: u32 = if table_exists(conn, "media")? {
        conn.query_row("SELECT count(*) FROM media", [], |row| row.get(0))?
    } else {
        0
    };
    let tombstone_count: u32 = if table_exists(conn, "tombstones")? {
        conn.query_row("SELECT count(*) FROM tombstones", [], |row| row.get(0))?
    } else {
        0
    };
    Ok(PackStatus {
        compatible: SUPPORTED_SCHEMA_VERSIONS.contains(&manifest.schema_version.as_str()),
        schema_version: manifest.schema_version,
        pack_version: manifest.pack_version,
        language: manifest.language,
        item_count: manifest.item_count,
        media_count,
        tombstone_count,
    })
}

/// Removed-item records: learner history referencing these ids stays
/// interpretable across pack updates.
pub fn list_tombstones(conn: &Connection) -> Result<Vec<TombstoneRecord>, CoreError> {
    if !table_exists(conn, "tombstones")? {
        return Ok(vec![]);
    }
    let mut stmt =
        conn.prepare("SELECT item_id, removed_in, reason FROM tombstones ORDER BY item_id")?;
    let rows = stmt
        .query_map([], |r| {
            Ok(TombstoneRecord {
                item_id: r.get(0)?,
                removed_in: r.get(1)?,
                reason: r.get(2)?,
            })
        })?
        .collect::<Result<_, _>>()?;
    Ok(rows)
}

/// Media inventory without the bytes (payloads reference by `path`).
pub fn list_media(conn: &Connection) -> Result<Vec<MediaInfo>, CoreError> {
    if !table_exists(conn, "media")? {
        return Ok(vec![]);
    }
    let mut stmt =
        conn.prepare("SELECT path, kind, sha256, length(bytes) FROM media ORDER BY path")?;
    let rows = stmt
        .query_map([], |r| {
            Ok(MediaInfo {
                path: r.get(0)?,
                kind: r.get(1)?,
                sha256: r.get(2)?,
                size_bytes: r.get(3)?,
            })
        })?
        .collect::<Result<_, _>>()?;
    Ok(rows)
}

/// One media asset, bytes included (the shell writes them to a temp
/// file or feeds them straight to a player/image view).
pub fn get_media(conn: &Connection, path: &str) -> Result<MediaBlob, CoreError> {
    if !table_exists(conn, "media")? {
        return Err(CoreError::NotFound {
            message: format!("media {path} (pack has no media table)"),
        });
    }
    conn.query_row(
        "SELECT kind, sha256, bytes FROM media WHERE path = ?1",
        [path],
        |r| {
            Ok(MediaBlob {
                kind: r.get(0)?,
                sha256: r.get(1)?,
                bytes: r.get(2)?,
            })
        },
    )
    .optional()?
    .ok_or_else(|| CoreError::NotFound {
        message: format!("media {path}"),
    })
}

pub fn read_manifest(conn: &Connection) -> Result<PackManifest, CoreError> {
    let get = |key: &str| -> Result<String, CoreError> {
        conn.query_row(
            "SELECT value FROM manifest WHERE key = ?1",
            [key],
            |row| row.get(0),
        )
        .optional()?
        .ok_or_else(|| CoreError::Invalid {
            message: format!("manifest missing key: {key}"),
        })
    };
    let item_count: u32 =
        conn.query_row("SELECT count(*) FROM items", [], |row| row.get(0))?;
    Ok(PackManifest {
        schema_version: get("schema_version")?,
        pack_version: get("pack_version")?,
        language: get("language")?,
        item_count,
    })
}

pub fn list_item_ids(conn: &Connection) -> Result<Vec<String>, CoreError> {
    let mut stmt = conn.prepare("SELECT id FROM items ORDER BY id")?;
    let ids = stmt
        .query_map([], |row| row.get(0))?
        .collect::<Result<Vec<String>, _>>()?;
    Ok(ids)
}

/// The authored side of a vocabulary card, keyed by the spec lemma its
/// evidence points at. Separate from `ItemMeta` because the browser needs
/// the payload's face, which `list_item_meta` deliberately leaves lazy.
#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct VocabCardRow {
    pub item_id: String,
    pub lemma: String,
    pub front: String,
    pub back: String,
    pub example: Option<String>,
    pub example_gloss: Option<String>,
}

#[derive(Deserialize)]
struct VocabCardPayload {
    #[serde(default)]
    lemma: String,
    #[serde(default)]
    front: String,
    #[serde(default)]
    back: String,
    #[serde(default)]
    example: Option<String>,
    #[serde(default)]
    example_gloss: Option<String>,
}

pub fn list_vocab_cards(conn: &Connection) -> Result<Vec<VocabCardRow>, CoreError> {
    let mut stmt = conn
        .prepare("SELECT id, payload FROM items WHERE item_type = 'vocab_card' ORDER BY id")?;
    let rows = stmt
        .query_map([], |r| {
            let id: String = r.get(0)?;
            let payload: String = r.get(1)?;
            let card: VocabCardPayload = serde_json::from_str(&payload).unwrap_or(
                VocabCardPayload {
                    lemma: String::new(),
                    front: String::new(),
                    back: String::new(),
                    example: None,
                    example_gloss: None,
                },
            );
            Ok(VocabCardRow {
                item_id: id,
                lemma: card.lemma,
                front: card.front,
                back: card.back,
                example: card.example,
                example_gloss: card.example_gloss,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(rows)
}

pub fn get_item_json(conn: &Connection, item_id: &str) -> Result<String, CoreError> {
    conn.query_row(
        "SELECT payload FROM items WHERE id = ?1",
        [item_id],
        |row| row.get(0),
    )
    .optional()?
    .ok_or_else(|| CoreError::NotFound {
        message: format!("item {item_id}"),
    })
}

pub fn score_attempt(
    conn: &Connection,
    item_id: &str,
    response: &str,
) -> Result<ScoreResult, CoreError> {
    let mut stmt = conn.prepare(
        "SELECT answer, is_canonical FROM acceptable_answers WHERE item_id = ?1",
    )?;
    let answers = stmt
        .query_map([item_id], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, bool>(1)?))
        })?
        .collect::<Result<Vec<(String, bool)>, _>>()?;
    if answers.is_empty() {
        return Err(CoreError::NotFound {
            message: format!("no acceptable answers for item {item_id}"),
        });
    }

    let norm = normalize(response);
    let matched = answers.iter().find(|(a, _)| normalize(a) == norm);
    let expected: Vec<String> = answers
        .iter()
        .filter(|(_, canonical)| *canonical)
        .map(|(a, _)| a.clone())
        .collect();

    if let Some((answer, _)) = matched {
        return Ok(ScoreResult {
            correct: true,
            matched_answer: Some(answer.clone()),
            expected,
            feedback: None,
        });
    }

    // Miss: prefer distractor-specific feedback, fall back to the item's
    // general explanation.
    let feedback: Option<String> = conn
        .query_row(
            "SELECT feedback FROM distractor_feedback
             WHERE item_id = ?1 AND response_norm = ?2",
            rusqlite::params![item_id, norm],
            |row| row.get(0),
        )
        .optional()?
        .or(conn
            .query_row(
                "SELECT feedback FROM explanations WHERE item_id = ?1",
                [item_id],
                |row| row.get(0),
            )
            .optional()?);

    Ok(ScoreResult {
        correct: false,
        matched_answer: None,
        expected,
        feedback,
    })
}
