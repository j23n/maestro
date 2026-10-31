"""Build the bundled content database from kaikki (and optionally Morph-it!)."""

from __future__ import annotations

import datetime as _dt
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from . import grammar, kaikki, morphit
from .normalize import fold
from .registry import Registry, headword_key, sense_fingerprint

SCHEMA_VERSION = "1"


@dataclass
class BuildStats:
    lemmas: int = 0
    senses: int = 0
    forms: int = 0
    retired_senses: int = 0
    unlinked_form_of: int = 0
    morphit_forms: int = 0


def create(path: str, schema_path: str) -> sqlite3.Connection:
    if os.path.exists(path):
        os.remove(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    with open(schema_path, encoding="utf-8") as fh:
        conn.executescript(fh.read())
    return conn


def build(
    conn: sqlite3.Connection,
    entries: list[kaikki.Entry],
    form_of: list[kaikki.FormOf],
    registry: Registry,
    morph: Iterable[morphit.MorphForm] = (),
    redirects: dict[str, str] | None = None,
    meta: dict[str, str] | None = None,
) -> BuildStats:
    stats = BuildStats()
    cur = conn.cursor()
    by_key: dict[tuple[str, str], list[str]] = defaultdict(list)  # (headword_key, pos) -> lemma ids
    by_headword: dict[str, list[str]] = defaultdict(list)
    forms_seen: set[tuple[str, str, str]] = set()

    def add_form(form: str, lemma_id: str, tag: str, source: str) -> None:
        key = (form, lemma_id, tag)
        if key in forms_seen:
            return
        forms_seen.add(key)
        cur.execute("INSERT INTO form (form, form_fold, lemma_id, tag, source) VALUES (?,?,?,?,?)",
                    (form, fold(form), lemma_id, tag, source))
        stats.forms += 1

    for e in entries:
        fingerprint = f"{headword_key(e.headword, e.pos)}|{e.pos}|{fold(e.senses[0].gloss)}"
        lemma_id = registry.lemma_id(e.headword, e.pos, fingerprint)
        by_key[(headword_key(e.headword, e.pos), e.pos)].append(lemma_id)
        by_headword[headword_key(e.headword, "x")].append(lemma_id)
        cur.execute(
            "INSERT INTO lemma (id, headword, headword_fold, pos, gender, plural, ipa, auxiliary) VALUES (?,?,?,?,?,?,?,?)",
            (lemma_id, e.headword, fold(e.headword), e.pos, e.gender, e.plural, e.ipa, e.auxiliary),
        )
        stats.lemmas += 1
        glosses = []
        for ord_, s in enumerate(e.senses):
            sid = registry.sense_id(lemma_id, sense_fingerprint(s.senseid, s.wikidata, lemma_id, s.gloss), s.gloss)
            cur.execute("INSERT OR IGNORE INTO sense (id, lemma_id, ord, gloss, tags) VALUES (?,?,?,?,?)",
                        (sid, lemma_id, ord_, s.gloss, " ".join(s.tags)))
            stats.senses += 1
            glosses.append(s.gloss)
            for it, en in s.examples:
                cur.execute("INSERT INTO example (sense_id, it, en) VALUES (?,?,?)", (sid, it, en))
        cur.execute("INSERT INTO lemma_fts (lemma_id, headword, glosses) VALUES (?,?,?)",
                    (lemma_id, e.headword, " ; ".join(glosses)))
        add_form(e.headword, lemma_id, "inf.pres" if e.pos == "v" else "", "kaikki")
        for form, tag in e.forms:
            add_form(form, lemma_id, tag, "kaikki")

    # Senses the registry knows but this dump lacks stay in the DB, retired (HANDOFF.md 6.5).
    known_lemmas = {lid for ids in by_key.values() for lid in ids}
    for sid, gloss in registry.retired_senses():
        lemma_id = sid.split("#", 1)[0]
        if lemma_id in known_lemmas:
            cur.execute("INSERT OR IGNORE INTO sense (id, lemma_id, ord, gloss, retired) VALUES (?,?,?,?,1)",
                        (sid, lemma_id, 999, gloss))
            stats.retired_senses += 1

    def resolve(lemma: str, pos: str) -> str | None:
        ids = by_key.get((headword_key(lemma, pos), pos))
        if ids:
            return ids[0]
        ids = by_headword.get(headword_key(lemma, "x"))
        return ids[0] if ids else None

    for fo in form_of:
        lemma_id = resolve(fo.lemma, fo.pos)
        if lemma_id is None:
            stats.unlinked_form_of += 1
            continue
        if not fo.tag and cur.execute("SELECT 1 FROM form WHERE form = ? AND lemma_id = ?",
                                      (fo.form, lemma_id)).fetchone():
            continue  # the lemma's own forms table already analyses it, with a tag
        add_form(fo.form, lemma_id, fo.tag, "kaikki")

    for mf in morph:
        lemma_id = resolve(mf.lemma, mf.pos)
        if lemma_id is None:
            continue
        before = stats.forms
        add_form(mf.form, lemma_id, mf.tag, "morphit")
        stats.morphit_forms += stats.forms - before

    for old, new in (redirects or {}).items():
        cur.execute("INSERT OR REPLACE INTO id_redirect (old_id, new_id) VALUES (?,?)", (old, new))

    info = {
        "schema_version": SCHEMA_VERSION,
        "content_version": _dt.date.today().strftime("%Y.%m.%d"),
        "lemmas": str(stats.lemmas),
        "senses": str(stats.senses),
        "forms": str(stats.forms),
    }
    info.update(meta or {})
    for key, value in info.items():
        cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))
    conn.commit()
    return stats


def add_grammar(conn: sqlite3.Connection, topics: list[grammar.Topic]) -> None:
    conn.executemany(
        "INSERT INTO grammar_topic (id, title, level, summary, body, ord) VALUES (?,?,?,?,?,?)",
        [(t.id, t.title, t.level, t.summary, t.body, t.order) for t in topics],
    )
    conn.commit()


def load_redirects(path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip() and not line.startswith("#"):
                    old, new = line.rstrip("\n").split("\t")[:2]
                    result[old] = new
    return result


def finish(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO lemma_fts(lemma_fts) VALUES ('optimize')")
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
