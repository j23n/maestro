"""Word frequencies: a form list (content/frequency/) turned into a rank per lemma."""

from __future__ import annotations

import os
import sqlite3
from collections import defaultdict

from .normalize import apostrophes, nfc


def load(path: str) -> dict[str, int]:
    """Form -> corpus count, lowercase NFC. Empty when the file is missing."""
    counts: dict[str, int] = {}
    if not os.path.exists(path):
        return counts
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) != 2 or not parts[1].isdigit():
                continue
            form = nfc(apostrophes(parts[0])).lower()
            counts[form] = counts.get(form, 0) + int(parts[1])
    return counts


def form_ranks(counts: dict[str, int]) -> dict[str, int]:
    """Form -> rank, 1 for the most frequent."""
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {form: n for n, (form, _) in enumerate(ordered, start=1)}


def lemma_counts(conn: sqlite3.Connection, counts: dict[str, int]) -> dict[str, float]:
    """Lemma ID -> summed count of its forms. A form shared by several lemmas splits its count evenly."""
    totals: dict[str, float] = defaultdict(float)
    for form, count in counts.items():
        lemmas = {row[0] for row in conn.execute(
            "SELECT DISTINCT f.lemma_id FROM form f JOIN lemma l ON l.id = f.lemma_id "
            "WHERE f.form = ? AND l.retired = 0 AND l.pos != 'propn'", (form,))}
        for lemma_id in lemmas:
            totals[lemma_id] += count / len(lemmas)
    return totals


def assign_ranks(conn: sqlite3.Connection, counts: dict[str, int]) -> int:
    """Writes lemma.freq_rank (1 = most frequent). Returns the number of ranked lemmas."""
    totals = lemma_counts(conn, counts)
    ordered = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    conn.execute("UPDATE lemma SET freq_rank = NULL")
    conn.executemany("UPDATE lemma SET freq_rank = ? WHERE id = ?",
                     [(n, lemma_id) for n, (lemma_id, _) in enumerate(ordered, start=1)])
    conn.commit()
    return len(ordered)
