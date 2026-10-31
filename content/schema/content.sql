-- Schema of the bundled, read-only content database (HANDOFF.md 6.2).
-- Built offline by tools/maestro_content; read by Packages/MaestroKit (LexiconKit).
-- Bump `schema_version` in meta when this file changes in a way the app must know about.

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per dictionary entry. id: it:<headword>:<pos>[:<n>] (HANDOFF.md 6.5).
CREATE TABLE lemma (
    id            TEXT PRIMARY KEY,
    headword      TEXT NOT NULL,
    headword_fold TEXT NOT NULL,          -- lowercase, accents removed
    pos           TEXT NOT NULL,          -- v n adj adv prep art conj pron det num intj propn phr contr
    gender        TEXT,                   -- m f mf
    plural        TEXT,
    ipa           TEXT,
    auxiliary     TEXT,                   -- verbs: essere | avere | both
    irregular     INTEGER NOT NULL DEFAULT 0,
    freq_rank     INTEGER,
    retired       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX lemma_headword ON lemma (headword);
CREATE INDEX lemma_headword_fold ON lemma (headword_fold);

-- Senses. id: <lemmaID>#<code>. Retired senses stay so old cards still render.
CREATE TABLE sense (
    id       TEXT PRIMARY KEY,
    lemma_id TEXT NOT NULL,
    ord      INTEGER NOT NULL,
    gloss    TEXT NOT NULL,
    tags     TEXT NOT NULL DEFAULT '',    -- space-separated Wiktionary tags (intransitive, figurative, ...)
    retired  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX sense_lemma ON sense (lemma_id, ord);

CREATE TABLE example (
    sense_id TEXT NOT NULL,
    it       TEXT NOT NULL,
    en       TEXT
);
CREATE INDEX example_sense ON example (sense_id);

-- Inflected forms. tag: a form tag (cond.pass.1p) for verbs, gender-number (mp) for nouns
-- and adjectives, '' for the base form.
CREATE TABLE form (
    form      TEXT NOT NULL,
    form_fold TEXT NOT NULL,
    lemma_id  TEXT NOT NULL,
    tag       TEXT NOT NULL DEFAULT '',
    source    TEXT NOT NULL DEFAULT ''    -- kaikki | morphit
);
CREATE INDEX form_form ON form (form);
CREATE INDEX form_form_fold ON form (form_fold);
CREATE INDEX form_lemma ON form (lemma_id);

CREATE TABLE id_redirect (
    old_id TEXT PRIMARY KEY,
    new_id TEXT NOT NULL
);

CREATE TABLE grammar_topic (
    id      TEXT PRIMARY KEY,
    title   TEXT NOT NULL,
    level   TEXT NOT NULL,
    summary TEXT NOT NULL,
    body    TEXT NOT NULL,                -- Markdown
    ord     INTEGER NOT NULL
);

-- Every text the app knows about, downloaded or not (HANDOFF.md 6.3).
CREATE TABLE catalog_text (
    id         TEXT PRIMARY KEY,
    pack_id    TEXT NOT NULL,
    title      TEXT NOT NULL,
    level      TEXT NOT NULL,
    collection TEXT NOT NULL,
    words      INTEGER NOT NULL,
    ord        INTEGER NOT NULL,
    bundled    INTEGER NOT NULL
);

CREATE TABLE text_lemma (
    text_id  TEXT NOT NULL,
    lemma_id TEXT NOT NULL,
    count    INTEGER NOT NULL,
    PRIMARY KEY (text_id, lemma_id)
);

CREATE VIRTUAL TABLE lemma_fts USING fts5 (
    lemma_id UNINDEXED,
    headword,
    glosses,
    tokenize = 'unicode61 remove_diacritics 2'
);
