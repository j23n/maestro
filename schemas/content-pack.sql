-- Italiano content pack — schema_version 1 (normative; see docs/03).
-- Created by the Python pipeline (content build), read by Swift (Storage/PackReader) in read-only mode.
-- Conventions: TEXT ids as in docs/03; JSON columns hold camelCase JSON; times in milliseconds.
-- Change process: edit this file, bump meta.schema_version, update PackReader and the pipeline in the same PR.

PRAGMA foreign_keys = ON;

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,   -- schema_version, pack_version, content_hash, git_sha, built_with, course_id, locale, release (0|1)
  value TEXT NOT NULL
);

CREATE TABLE units (
  id          TEXT PRIMARY KEY,                -- u00 … u12, u99 (final review)
  ord         INTEGER NOT NULL UNIQUE,
  title_it    TEXT NOT NULL,
  title_en    TEXT NOT NULL,
  episode_en  TEXT NOT NULL,
  est_minutes INTEGER NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('unit', 'final'))
);

CREATE TABLE can_dos (
  id         TEXT PRIMARY KEY,                 -- cd:…
  unit_id    TEXT NOT NULL REFERENCES units(id),
  ord        INTEGER NOT NULL,
  text_en    TEXT NOT NULL,
  cefr_scale TEXT,
  stretch    INTEGER NOT NULL DEFAULT 0 CHECK (stretch IN (0, 1))
);

CREATE TABLE syllabus_items (
  id       TEXT PRIMARY KEY,                   -- sy:…
  area     TEXT NOT NULL CHECK (area IN ('gr', 'fn', 'tp', 'ss', 'cefr', 'ex')),
  label_en TEXT NOT NULL
);

CREATE TABLE syllabus_trace (
  syllabus_id TEXT NOT NULL REFERENCES syllabus_items(id),
  role        TEXT NOT NULL CHECK (role IN ('introduced', 'practised', 'assessed')),
  unit_id     TEXT REFERENCES units(id),
  ref         TEXT NOT NULL,                   -- step, exercise or item id that satisfies the role
  PRIMARY KEY (syllabus_id, role, ref)
);

CREATE TABLE audio (
  id          TEXT PRIMARY KEY,                -- a:<12 hex>
  file        TEXT NOT NULL,                   -- '<12 hex>.m4a', relative to Content/Audio/ (no colon in file names)
  duration_ms INTEGER NOT NULL,
  voice       TEXT NOT NULL,
  sha256      TEXT NOT NULL
);

CREATE TABLE items (
  id             TEXT PRIMARY KEY,             -- w:… c:… g:… s:…
  kind           TEXT NOT NULL CHECK (kind IN ('word', 'chunk', 'grammar', 'sound')),
  it             TEXT NOT NULL,                -- lemma, chunk text, grammar title or sound label
  display_indef  TEXT,                         -- nouns: 'un cornetto' (used in generated answers)
  display_def    TEXT,                         -- nouns: 'il cornetto', 'l'acqua (f)'; the display form (docs/03)
  recall_answer  TEXT,                         -- answer pattern for generated recall cards, or NULL for the default
  gloss_en       TEXT NOT NULL,
  alt_glosses_en TEXT NOT NULL DEFAULT '[]',   -- JSON array
  note_en        TEXT,
  pos            TEXT,
  gender         TEXT CHECK (gender IN ('m', 'f', 'mf') OR gender IS NULL),
  plural         TEXT,
  unit_id        TEXT NOT NULL REFERENCES units(id),
  lesson_id      TEXT,                         -- where introduced
  topics         TEXT NOT NULL DEFAULT '[]',   -- JSON array of topic ids
  audio_id       TEXT REFERENCES audio(id),
  flags          INTEGER NOT NULL DEFAULT 0    -- 1 cognate, 2 false friend
);

CREATE TABLE item_skills (
  item_id   TEXT NOT NULL REFERENCES items(id),
  skill     TEXT NOT NULL CHECK (skill IN ('read', 'listen', 'recall', 'speak')),
  status    TEXT NOT NULL CHECK (status IN ('P', 'R', 'chunk')),
  scheduled INTEGER NOT NULL CHECK (scheduled IN (0, 1)),   -- docs/05 § Skills and what gets scheduled
  PRIMARY KEY (item_id, skill)
);

CREATE TABLE item_requires (
  item_id     TEXT NOT NULL REFERENCES items(id),
  requires_id TEXT NOT NULL REFERENCES items(id),
  PRIMARY KEY (item_id, requires_id)
);

CREATE TABLE forms (                            -- surface forms that occur in course content (for writing feedback)
  form    TEXT NOT NULL,                        -- normalised, lowercase
  item_id TEXT NOT NULL REFERENCES items(id),
  morph   TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (form, item_id, morph)
);

CREATE TABLE sounds (
  item_id TEXT PRIMARY KEY REFERENCES items(id),
  pairs   TEXT NOT NULL                         -- JSON [[ "pena", "penna" ], …] with audio ids: [[{"it":"pena","audioId":"a:…"}, …]]
);

CREATE TABLE characters (
  id             TEXT PRIMARY KEY,              -- ch:…, plus the reserved ch:narrator and ch:announcer
  name           TEXT NOT NULL,
  description_en TEXT NOT NULL
);

CREATE TABLE countries (
  id             TEXT PRIMARY KEY,              -- ISO 3166-1 alpha-2, lowercase; gb-eng, gb-sct, gb-wls, gb-nir (ISO 3166-2)
  name_en        TEXT NOT NULL,
  name_it        TEXT NOT NULL,
  home_phrase_it TEXT NOT NULL,                 -- 'negli Stati Uniti', 'in Canada'
  alt_home_phrases_it TEXT NOT NULL DEFAULT '[]', -- JSON array, accepted in answers, never shown ('in America')
  nationality_m  TEXT NOT NULL,
  nationality_f  TEXT NOT NULL
);

CREATE TABLE lessons (
  id          TEXT PRIMARY KEY,                 -- u02.l1
  unit_id     TEXT NOT NULL REFERENCES units(id),
  ord         INTEGER NOT NULL,
  title_it    TEXT NOT NULL,
  title_en    TEXT NOT NULL,
  est_minutes INTEGER NOT NULL,
  UNIQUE (unit_id, ord)
);

CREATE TABLE steps (
  id          TEXT PRIMARY KEY,
  unit_id     TEXT NOT NULL REFERENCES units(id),
  lesson_id   TEXT REFERENCES lessons(id),      -- NULL for unit-level steps (opener, task steps, check, fluency)
  ord         INTEGER NOT NULL,                 -- order within the unit; course order = (units.ord, steps.ord)
  kind        TEXT NOT NULL CHECK (kind IN ('opener', 'preview', 'story', 'listening', 'reading', 'note', 'practice',
                                            'sounds', 'use', 'conversation', 'talk', 'writing', 'relay', 'fluency', 'check')),
  title_en    TEXT,
  payload     TEXT NOT NULL,                    -- JSON per kind (docs/06)
  est_seconds INTEGER NOT NULL,
  strand      TEXT NOT NULL CHECK (strand IN ('input', 'output', 'language-focus', 'fluency', 'assessment')),
  draft       INTEGER NOT NULL DEFAULT 0,       -- 1 in dev packs for unapproved content
  UNIQUE (unit_id, ord)
);

CREATE TABLE step_introduces (
  step_id TEXT NOT NULL REFERENCES steps(id),
  item_id TEXT NOT NULL REFERENCES items(id),
  skill   TEXT NOT NULL CHECK (skill IN ('read', 'listen', 'recall', 'speak')),
  PRIMARY KEY (step_id, item_id, skill)
);

CREATE TABLE texts (
  id          TEXT PRIMARY KEY,
  unit_id     TEXT NOT NULL REFERENCES units(id),
  kind        TEXT NOT NULL CHECK (kind IN ('story', 'dialogue', 'announcement', 'phone', 'message', 'real_world', 'model')),
  title_it    TEXT,
  title_en    TEXT,
  layout      TEXT,                             -- JSON for real_world texts (docs/06 § Real-world reading)
  audio_id    TEXT REFERENCES audio(id),
  duration_ms INTEGER
);

CREATE TABLE text_lines (
  text_id      TEXT NOT NULL REFERENCES texts(id),
  ord          INTEGER NOT NULL,
  speaker_id   TEXT REFERENCES characters(id),  -- ch:…, ch:narrator or ch:announcer; NULL only in real-world texts
  addressee_id TEXT REFERENCES characters(id),
  register     TEXT CHECK (register IN ('tu', 'lei') OR register IS NULL),
  it           TEXT NOT NULL,
  en           TEXT NOT NULL,
  start_ms     INTEGER,
  end_ms       INTEGER,
  PRIMARY KEY (text_id, ord)
);

CREATE TABLE tokens (
  text_id  TEXT NOT NULL REFERENCES texts(id),
  line_ord INTEGER NOT NULL,
  ord      INTEGER NOT NULL,
  surface  TEXT NOT NULL,
  trailing TEXT NOT NULL DEFAULT '',            -- spaces and punctuation after the token, for exact re-rendering
  kind     TEXT NOT NULL CHECK (kind IN ('word', 'punct', 'name', 'number', 'foreign')),
  item_id  TEXT REFERENCES items(id),
  gloss_en TEXT,                                -- context gloss; falls back to items.gloss_en
  flags    INTEGER NOT NULL DEFAULT 0,          -- 1 new in this text, 2 recognise-only form, 4 lesson target grammar
  start_ms INTEGER,
  end_ms   INTEGER,
  PRIMARY KEY (text_id, line_ord, ord)
);

CREATE TABLE text_requires (
  text_id TEXT NOT NULL REFERENCES texts(id),
  item_id TEXT NOT NULL REFERENCES items(id),
  skill   TEXT NOT NULL CHECK (skill IN ('read', 'listen', 'recall', 'speak')),
  PRIMARY KEY (text_id, item_id, skill)
);

CREATE TABLE grammar_notes (
  id       TEXT PRIMARY KEY,                    -- u02.l1.note
  unit_id  TEXT NOT NULL REFERENCES units(id),
  step_id  TEXT NOT NULL REFERENCES steps(id),
  title_en TEXT NOT NULL,
  body     TEXT NOT NULL                        -- JSON blocks (docs/06 § Grammar note), examples resolved to token arrays
);

CREATE TABLE note_items (                       -- a note may introduce several grammar points
  note_id TEXT NOT NULL REFERENCES grammar_notes(id),
  item_id TEXT NOT NULL REFERENCES items(id),   -- g:…
  ord     INTEGER NOT NULL,
  PRIMARY KEY (note_id, item_id)
);

CREATE TABLE exercises (
  id          TEXT PRIMARY KEY,
  format      TEXT NOT NULL CHECK (format IN ('cloze', 'recall', 'sentence-building', 'dictation', 'sound-pair', 'repeat',
                                              'choice', 'match', 'true-false', 'relay', 'conversation', 'talk', 'writing')),
  unit_id     TEXT NOT NULL REFERENCES units(id),
  step_id     TEXT REFERENCES steps(id),
  role        TEXT NOT NULL CHECK (role IN ('learn', 'check', 'placement', 'final', 'comprehension')),
  payload     TEXT NOT NULL,                    -- JSON per format (docs/06)
  score       INTEGER NOT NULL DEFAULT 1,      -- points in checks (talk/writing/conversation may score >1)
  est_seconds INTEGER NOT NULL,
  source_ref  TEXT                              -- 'u02.l1.story#3'
);

CREATE TABLE exercise_targets (
  exercise_id TEXT NOT NULL REFERENCES exercises(id),
  item_id     TEXT NOT NULL REFERENCES items(id),
  skill       TEXT NOT NULL CHECK (skill IN ('read', 'listen', 'recall', 'speak')),
  PRIMARY KEY (exercise_id, item_id, skill)
);

CREATE TABLE exercise_requires (
  exercise_id TEXT NOT NULL REFERENCES exercises(id),
  item_id     TEXT NOT NULL REFERENCES items(id),
  skill       TEXT NOT NULL CHECK (skill IN ('read', 'listen', 'recall', 'speak')),
  PRIMARY KEY (exercise_id, item_id, skill)
);

CREATE TABLE assessments (                      -- course-level tests that aren't unit steps (docs/06 §19, §20)
  id      TEXT PRIMARY KEY CHECK (id IN ('placement', 'final')),
  payload TEXT NOT NULL                         -- JSON: placement blocks or final-check sections, with exercise ids
);

CREATE TABLE exercise_tags (
  exercise_id TEXT NOT NULL REFERENCES exercises(id),
  tag         TEXT NOT NULL,                    -- cd:… or sy:…
  PRIMARY KEY (exercise_id, tag)
);

CREATE INDEX steps_by_lesson        ON steps(lesson_id, ord);
CREATE INDEX exercises_by_step      ON exercises(step_id);
CREATE INDEX exercise_targets_item  ON exercise_targets(item_id, skill);
CREATE INDEX exercise_requires_item ON exercise_requires(item_id, skill);
CREATE INDEX items_by_unit          ON items(unit_id);
CREATE INDEX tokens_by_item         ON tokens(item_id);
CREATE INDEX forms_by_item          ON forms(item_id);
CREATE INDEX note_items_by_item     ON note_items(item_id);
