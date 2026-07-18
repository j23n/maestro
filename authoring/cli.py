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
    sub.choices["build"].add_argument("--out", default="build/it.pack.sqlite")
    sub.choices["generate"].add_argument("--gp", required=True, help="grammar point id")
    sub.choices["generate"].add_argument("--count", type=int, default=10)
    sub.choices["generate"].add_argument(
        "--from-file",
        type=Path,
        default=None,
        help="parse a prepared model response instead of calling the API",
    )
    sub.choices["generate"].add_argument("--model", default=None)
    sub.choices["review"].add_argument("--port", type=int, default=8321)

    args = parser.parse_args()
    pack_dir = Path(args.pack)
    lang = yaml.safe_load((pack_dir / "pack.yaml").read_text())["language"]
    spec_dir = Path("spec") / lang

    if args.command == "validate":
        from authoring.build_pack import load_pack_sources, validate_pack
        from authoring.validate_spec import load_spec, validate

        spec = load_spec(spec_dir)
        errors, warnings = validate(spec)
        _m, drills, readings, listenings = load_pack_sources(pack_dir)
        errors += validate_pack([*drills, *readings, *listenings], spec)
        for w in warnings:
            print(f"warning: {w}")
        for e in errors:
            print(f"ERROR: {e}")
        print(f"{len(errors)} errors, {len(warnings)} warnings")
        return 1 if errors else 0

    if args.command == "build":
        from authoring.build_pack import build

        return build(pack_dir, spec_dir, Path(args.out))

    if args.command == "generate":
        from authoring.generate import DEFAULT_MODEL, generate_drills
        from authoring.validate_spec import load_spec

        generate_drills(
            pack_dir,
            load_spec(spec_dir),
            args.gp,
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
