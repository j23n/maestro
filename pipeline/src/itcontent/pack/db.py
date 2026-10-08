"""Writing the pack's SQLite file and its canonical hash (docs/04 § Pack build).

The database is created in memory from `schemas/content-pack.sql`, rows are inserted sorted by primary key, foreign
keys are checked, and `VACUUM INTO` writes the destination (rollback journal, so the app can open it read-only).

**Pack hash:** sha256 of a canonical dump of every table in name order: a header line `table(col,…)`, then each row
as a JSON array, rows ordered by primary key; the `meta` keys `content_hash`, `git_sha` and `built_with` are left
out. `meta.content_hash` stores the value, so two builds of the same input have the same hash whatever commit or
pipeline version built them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from itcontent import paths
from itcontent.pack.common import BuildError

HASH_EXCLUDED_META = ("content_hash", "git_sha", "built_with")
# Parents before children, so the foreign-key check reads naturally; every table of the DDL is listed.
TABLE_ORDER = (
    "meta",
    "units",
    "can_dos",
    "syllabus_items",
    "syllabus_trace",
    "audio",
    "items",
    "item_skills",
    "item_requires",
    "forms",
    "sounds",
    "characters",
    "countries",
    "lessons",
    "steps",
    "step_introduces",
    "texts",
    "text_lines",
    "tokens",
    "text_requires",
    "grammar_notes",
    "note_items",
    "exercises",
    "exercise_targets",
    "exercise_requires",
    "exercise_tags",
    "assessments",
)


def ddl(path: Path | None = None) -> str:
    return (path or paths.PACK_SQL).read_text(encoding="utf-8")


def schema_version(path: Path | None = None) -> int:
    """`meta.schema_version` as the normative DDL's header states it ("schema_version 1")."""
    m = re.search(r"schema_version\s+(\d+)", ddl(path))
    if not m:
        raise BuildError("schemas/content-pack.sql doesn't state its schema_version")
    return int(m.group(1))


def columns(con: sqlite3.Connection, table: str) -> tuple[list[str], list[str]]:
    """(all columns, primary-key columns in key order)."""
    info = con.execute(f"PRAGMA table_info({table})").fetchall()
    cols = [r[1] for r in info]
    pk = [r[1] for r in sorted((r for r in info if r[5]), key=lambda r: r[5])]
    return cols, pk or cols


def tables(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]


def _sort_key(row: Sequence[Any], idx: list[int]) -> tuple[Any, ...]:
    return tuple((0, row[i]) if isinstance(row[i], int | float) else (1, str(row[i])) for i in idx)


def create(rows: Mapping[str, Sequence[tuple[Any, ...]]], meta: Mapping[str, str]) -> sqlite3.Connection:
    """An in-memory pack with every row inserted and the foreign keys checked."""
    con = sqlite3.connect(":memory:")
    con.executescript(ddl())
    con.execute("PRAGMA foreign_keys = OFF")  # checked once below, with readable messages
    known = set(tables(con))
    unknown = set(rows) - known
    if unknown:
        raise BuildError(f"rows for tables the DDL doesn't define: {', '.join(sorted(unknown))}")
    missing = known - set(TABLE_ORDER)
    if missing:
        raise BuildError(f"the DDL has tables the builder doesn't fill: {', '.join(sorted(missing))}")
    all_rows = {**rows, "meta": sorted(meta.items())}
    for table in TABLE_ORDER:
        cols, pk = columns(con, table)
        idx = [cols.index(c) for c in pk]
        data = sorted(all_rows.get(table, ()), key=lambda r: _sort_key(r, idx))
        for r in data:
            if len(r) != len(cols):
                raise BuildError(f"{table}: a row has {len(r)} values for {len(cols)} columns: {r!r}")
        try:
            con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})", data)
        except sqlite3.IntegrityError as exc:
            seen: dict[tuple[Any, ...], tuple[Any, ...]] = {}
            for r in data:
                key = tuple(r[i] for i in idx)
                if key in seen:
                    raise BuildError(f"{table}: two rows with the key {key!r}: {seen[key]!r} and {r!r}") from exc
                seen[key] = r
            raise BuildError(f"{table}: {exc}") from exc
    problems = []
    for table, rowid, parent, fk in con.execute("PRAGMA foreign_key_check"):
        cols, _ = columns(con, table)
        row = con.execute(f"SELECT * FROM {table} WHERE rowid = ?", (rowid,)).fetchone()
        ref = con.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        col = next((r[3] for r in ref if r[0] == fk), "?")
        value = row[cols.index(col)] if row and col in cols else "?"
        problems.append(f"{table}.{col} = {value!r} names no row of {parent} (row {row!r})")
    if problems:
        shown = "\n  ".join(problems[:20])
        more = f"\n  … and {len(problems) - 20} more" if len(problems) > 20 else ""
        raise BuildError(f"{len(problems)} reference(s) to missing rows:\n  {shown}{more}")
    con.commit()
    return con


def canonical_hash(con: sqlite3.Connection) -> str:
    h = hashlib.sha256()
    for table in tables(con):
        cols, pk = columns(con, table)
        h.update(f"{table}({','.join(cols)})\n".encode())
        where = ""
        if table == "meta":
            where = f" WHERE key NOT IN ({', '.join(repr(k) for k in HASH_EXCLUDED_META)})"
        for row in con.execute(f"SELECT * FROM {table}{where} ORDER BY {', '.join(pk)}"):
            h.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode())
            h.update(b"\n")
    return h.hexdigest()


def write(con: sqlite3.Connection, dest: Path) -> None:
    """VACUUM INTO a temporary file next to `dest`, then replace `dest` (never a half-written pack)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)
    con.execute("VACUUM INTO ?", (str(tmp),))
    check = sqlite3.connect(tmp)
    try:
        mode = check.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        check.close()
    if mode != "delete":
        tmp.unlink(missing_ok=True)
        raise BuildError(f"the pack was written with journal_mode={mode}, not delete")
    os.replace(tmp, dest)


def pack_hash(path: Path) -> str:
    """The canonical hash of a pack file (`content pack-hash`)."""
    if not path.is_file():
        raise BuildError(f"{path}: no such pack (run `make pack`)")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return canonical_hash(con)
    finally:
        con.close()


def counts(con: sqlite3.Connection) -> dict[str, int]:
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables(con)}
