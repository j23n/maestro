"""maestro-pack — the authoring CLI (plan §5 Phase 2).

Subcommands:
    validate    validate spec + pack sources
    build       compile packs/<lang> -> SQLite bundle
    generate    LLM-draft a drill bank for a grammar point
    review      launch the review web app (localhost)
    release     build + stamp a versioned release directory

Run as ``python -m authoring.cli <subcommand>`` from the repo root.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(prog="maestro-pack")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("validate", "build", "generate", "review", "release"):
        p = sub.add_parser(name)
        p.add_argument("--pack", default="packs/it", help="pack source dir")
    val = sub.choices["validate"]
    val.add_argument(
        "--quality",
        action="store_true",
        help="run content-quality checks (vocab level, solvability, "
        "near-duplicates, orthography) — warnings, not errors",
    )
    val.add_argument(
        "--adversarial",
        action="store_true",
        help="second-model adversarial answer pass over drills (API)",
    )
    val.add_argument(
        "--adversarial-from-file",
        type=Path,
        default=None,
        help="parse a prepared adversarial response instead of calling the API",
    )
    sub.choices["build"].add_argument("--out", default="build/it.pack.sqlite")
    gen = sub.choices["generate"]
    gen.add_argument(
        "--type",
        default="drill",
        choices=(
            "drill",
            "reading",
            "listening",
            "vocab",
            "speaking",
            "writing",
            "grammar_ref",
        ),
        help="item family to draft",
    )
    scope = gen.add_mutually_exclusive_group(required=True)
    scope.add_argument("--gp", help="grammar point id")
    scope.add_argument("--scenario", help="scenario id")
    scope.add_argument("--cando", help="can-do id")
    scope.add_argument("--theme", help='free theme, e.g. "Ferragosto" (needs --level)')
    gen.add_argument("--level", default=None, help="CEFR level (required for --theme)")
    gen.add_argument("--count", type=int, default=10)
    gen.add_argument(
        "--from-file",
        type=Path,
        default=None,
        help="parse a prepared model response instead of calling the API",
    )
    gen.add_argument("--model", default=None)
    sub.choices["review"].add_argument("--port", type=int, default=8321)

    args = parser.parse_args()
    pack_dir = Path(args.pack)
    lang = yaml.safe_load((pack_dir / "pack.yaml").read_text())["language"]
    spec_dir = Path("spec") / lang

    if args.command == "validate":
        from authoring.build_pack import (
            load_pack_sources,
            validate_media,
            validate_pack,
            validate_tombstones,
        )
        from authoring.validate_spec import load_spec, validate

        spec = load_spec(spec_dir)
        errors, warnings = validate(spec)
        sources = load_pack_sources(pack_dir)
        errors += validate_pack(sources.all_items(), spec)
        errors += validate_media(sources.all_items(), pack_dir)
        errors += validate_tombstones(sources)
        quality: dict[str, list[str]] = {}
        if args.quality:
            from authoring.quality import validate_quality

            quality = validate_quality(sources.all_items(), spec)
        if args.adversarial or args.adversarial_from_file:
            from authoring.quality import check_adversarial

            if args.adversarial_from_file:
                canned = args.adversarial_from_file.read_text()
                complete = lambda _prompt: canned  # noqa: E731
            else:
                from authoring.generate import call_api

                complete = call_api
            for k, v in check_adversarial(sources.all_items(), complete).items():
                quality.setdefault(k, []).extend(v)
        for w in warnings:
            print(f"warning: {w}")
        n_quality = 0
        for item_id, msgs in sorted(quality.items()):
            for m in msgs:
                print(f"warning: {item_id}: {m}")
                n_quality += 1
        for e in errors:
            print(f"ERROR: {e}")
        print(f"{len(errors)} errors, {len(warnings) + n_quality} warnings")
        return 1 if errors else 0

    if args.command == "build":
        from authoring.build_pack import build

        return build(pack_dir, spec_dir, Path(args.out))

    if args.command == "generate":
        from authoring.generate import DEFAULT_MODEL, generate_items, resolve_scope
        from authoring.validate_spec import load_spec

        spec = load_spec(spec_dir)
        scope_obj = resolve_scope(
            spec,
            gp=args.gp,
            scenario=args.scenario,
            cando=args.cando,
            theme=args.theme,
            level=args.level,
        )
        generate_items(
            pack_dir,
            spec,
            args.type,
            scope_obj,
            args.count,
            from_file=args.from_file,
            model=args.model or DEFAULT_MODEL,
        )
        return 0

    if args.command == "review":
        import uvicorn

        from authoring.review import create_app

        uvicorn.run(create_app(pack_dir, spec_dir), port=args.port)
        return 0

    if args.command == "release":
        from authoring.release import release

        return release(pack_dir, spec_dir, Path("build/release"))

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
