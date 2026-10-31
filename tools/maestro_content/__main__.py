"""python3 -m maestro_content build --kaikki FILE --out DIR [--morphit FILE] [--ids DIR] [--save-ids]"""

from __future__ import annotations

import argparse
import os
import sys

from . import build_db, curriculum, frequency, grammar, kaikki, morphit, packs
from .registry import Registry

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="maestro_content")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build content.sqlite and the text packs")
    b.add_argument("--kaikki", required=True, help="kaikki.org Italian JSONL (.jsonl or .jsonl.gz)")
    b.add_argument("--morphit", help="Morph-it! lexicon (optional)")
    b.add_argument("--out", required=True, help="output folder (gets content.sqlite and packs/)")
    b.add_argument("--ids", default=os.path.join(ROOT, "content", "ids"), help="ID registry folder")
    b.add_argument("--save-ids", action="store_true", help="write the updated registry back")
    b.add_argument("--texts", default=os.path.join(ROOT, "content", "texts"))
    b.add_argument("--grammar", default=os.path.join(ROOT, "content", "grammar"))
    b.add_argument("--frequency", default=os.path.join(ROOT, "content", "frequency", "it-opensubtitles-2018.txt"),
                   help="word-frequency list (form count per line)")
    b.add_argument("--dump-date", default="", help="date of the kaikki dump, recorded in meta")
    b.add_argument("--strict", action="store_true", help="fail on linker warnings too")

    default_db = os.path.join(ROOT, "App", "Resources", "Content", "content.sqlite")
    for name, text in (("coverage", "write the coverage report"), ("check", "check texts against their level and brief"),
                       ("brief", "propose a brief for the next text")):
        c = sub.add_parser(name, help=text)
        c.add_argument("--db", default=default_db, help="content.sqlite from make content")
        c.add_argument("--texts", default=os.path.join(ROOT, "content", "texts"))
        c.add_argument("--curriculum", default=os.path.join(ROOT, "content", "curriculum"))
        c.add_argument("--grammar", default=os.path.join(ROOT, "content", "grammar"))
        c.add_argument("--frequency", default=os.path.join(ROOT, "content", "frequency", "it-opensubtitles-2018.txt"))
        if name == "coverage":
            c.add_argument("--out", default=os.path.join(ROOT, ".build", "coverage.md"))
        elif name == "check":
            c.add_argument("paths", nargs="*", help="text sources; default: every text")
        else:
            c.add_argument("--level", required=True, choices=curriculum.LEVELS)
            c.add_argument("--collection", required=True)
            c.add_argument("--title", default="Senza titolo")
            c.add_argument("--window", default="", help="feature window, such as 12-01..01-06")
    args = ap.parse_args(argv)
    if args.cmd != "build":
        return curriculum_command(args)

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    db_path = os.path.join(out, "content.sqlite")
    conn = build_db.create(db_path, os.path.join(ROOT, "content", "schema", "content.sql"))
    registry = Registry.load(args.ids)

    print(f"reading {args.kaikki}", flush=True)
    entries, form_of = kaikki.read(kaikki.open_jsonl(args.kaikki))
    morph = list(morphit.read(args.morphit)) if args.morphit and os.path.exists(args.morphit) else []
    stats = build_db.build(conn, entries, form_of, registry, morph,
                           redirects=build_db.load_redirects(os.path.join(args.ids, "redirects.tsv")),
                           meta={"kaikki_dump": args.dump_date, "morphit": "yes" if morph else "no"})
    print(f"lemmas {stats.lemmas}, senses {stats.senses} (+{stats.retired_senses} retired), forms {stats.forms} "
          f"(morphit {stats.morphit_forms}), unlinked form-of {stats.unlinked_form_of}", flush=True)

    ranked = frequency.assign_ranks(conn, frequency.load(args.frequency))
    print(f"frequency ranks for {ranked} lemmas")

    topics = grammar.load_all(args.grammar)
    build_db.add_grammar(conn, topics)
    print(f"grammar topics {len(topics)}")

    content_version = conn.execute("SELECT value FROM meta WHERE key = 'content_version'").fetchone()[0]
    warnings, errors = packs.build_all(conn, args.texts, os.path.join(out, "packs"), content_version)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    print(f"texts: {conn.execute('SELECT count(*) FROM catalog_text').fetchone()[0]}, "
          f"{len(warnings)} linker warnings, {len(errors)} errors")
    build_db.finish(conn)
    if args.save_ids:
        registry.save(args.ids)
    size = os.path.getsize(db_path) / 1e6
    print(f"wrote {db_path} ({size:.1f} MB)")
    if errors or (args.strict and warnings):
        return 1
    return 0


def curriculum_command(args: argparse.Namespace) -> int:
    import sqlite3

    if not os.path.exists(args.db):
        print(f"{args.db} is missing; run make content first", file=sys.stderr)
        return 2
    conn = sqlite3.connect(args.db)
    row = conn.execute("SELECT value FROM meta WHERE key = 'kaikki_dump'").fetchone()
    sample = not (row and row[0])
    if sample:
        print("warning: the content database was built from the sample dictionary; most words won't link "
              "(make content CONTENT=full)", file=sys.stderr)
    extra = list(getattr(args, "paths", []) or [])
    lib = curriculum.load_library(conn, args.texts, args.curriculum, args.grammar, args.frequency, extra=extra)

    if args.cmd == "coverage":
        text = curriculum.report(lib, curriculum.coverage(lib, conn), sample)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.out}")
        return 0

    if args.cmd == "brief":
        rel, content = curriculum.propose_brief(lib, conn, args.level, args.collection, args.title, args.window)
        path = os.path.join(args.texts, rel)
        if os.path.exists(path):
            print(f"{path} exists", file=sys.stderr)
            return 1
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(path)
        print(content)
        return 0

    wanted = {os.path.abspath(p) for p in extra}
    texts = [t for t in lib.texts if not wanted or os.path.abspath(t.path) in wanted]
    missing = wanted - {os.path.abspath(t.path) for t in texts}
    for p in sorted(missing):
        print(f"error: {p}: not a text (a brief has no text to check yet)")
    failed = bool(missing)
    for t in texts:
        findings = curriculum.check_text(lib, t)
        errors = [f for f in findings if f.error]
        print(f"{t.id} ({t.level}, {t.status}): {'ok' if not errors else f'{len(errors)} errors'}")
        for f in findings:
            print(f"  {f}")
        failed = failed or bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
