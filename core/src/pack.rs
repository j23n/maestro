//! Read-only access to a content pack bundle (one SQLite file).
//!
//! Phase 0 bundle schema (grows in Phase 2's `maestro-pack build`):
//!
//! ```sql
//! CREATE TABLE manifest (key TEXT PRIMARY KEY, value TEXT NOT NULL);
//! CREATE TABLE items (
//!     id         TEXT PRIMARY KEY,   -- stable forever
//!     item_type  TEXT NOT NULL,      -- drill_cloze, reading, ...
//!     cefr_level TEXT NOT NULL,
//!     modality   TEXT NOT NULL,      -- reading, listening, writing, speaking
//!     payload    TEXT NOT NULL       -- JSON, shape depends on item_type
//! );
//! CREATE TABLE acceptable_answers (
//!     item_id      TEXT NOT NULL REFERENCES items(id),
//!     answer       TEXT NOT NULL,    -- stored pre-normalized at build time
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
//! ```

use rusqlite::{Connection, OpenFlags, OptionalExtension};
use serde::Deserialize;

use crate::normalize::normalize;
use crate::{CoreError, PackManifest, ScoreResult};

// --------------------------------------------------------------------------
// Curriculum spec tables, embedded in the bundle by `authoring/build_pack.py`
// so the composer has the DAG and decompositions offline.

#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct SpecGrammar {
    pub id: String,
    pub cefr_level: String,
    pub prerequisites: Vec<String>,
}

#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct SpecFunction {
    pub id: String,
    pub cefr_level: String,
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
}

#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct SpecData {
    pub grammar: Vec<SpecGrammar>,
    pub functions: Vec<SpecFunction>,
    pub scenarios: Vec<SpecScenario>,
    pub can_dos: Vec<SpecCanDo>,
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
    let mut stmt = conn.prepare("SELECT id, cefr_level, prerequisites FROM spec_grammar")?;
    spec.grammar = stmt
        .query_map([], |r| {
            Ok(SpecGrammar {
                id: r.get(0)?,
                cefr_level: r.get(1)?,
                prerequisites: json_vec(&r.get::<_, String>(2)?),
            })
        })?
        .collect::<Result<_, _>>()?;
    let mut stmt = conn.prepare("SELECT id, cefr_level FROM spec_functions")?;
    spec.functions = stmt
        .query_map([], |r| {
            Ok(SpecFunction {
                id: r.get(0)?,
                cefr_level: r.get(1)?,
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
    let mut stmt = conn.prepare(
        "SELECT id, cefr_level, skill, grammar_ids, function_ids FROM spec_can_dos",
    )?;
    spec.can_dos = stmt
        .query_map([], |r| {
            Ok(SpecCanDo {
                id: r.get(0)?,
                cefr_level: r.get(1)?,
                skill: r.get(2)?,
                grammar_ids: json_vec(&r.get::<_, String>(3)?),
                function_ids: json_vec(&r.get::<_, String>(4)?),
            })
        })?
        .collect::<Result<_, _>>()?;
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
    Ok(conn)
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
