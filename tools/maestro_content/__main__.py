"""python3 -m maestro_content build --kaikki FILE --out DIR [--morphit FILE] [--ids DIR] [--save-ids]"""

from __future__ import annotations

import argparse
import os
import sys

from . import build_db, grammar, kaikki, morphit, packs
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
    b.add_argument("--dump-date", default="", help="date of the kaikki dump, recorded in meta")
    b.add_argument("--strict", action="store_true", help="fail on linker warnings too")
    args = ap.parse_args(argv)

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


if __name__ == "__main__":
    sys.exit(main())
