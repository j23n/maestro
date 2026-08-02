"""maestro-pack — the authoring CLI (plan §5 Phase 2).

Subcommands:
    validate    validate spec + pack sources
    build       compile packs/<lang> -> SQLite bundle
    generate    LLM-draft a drill bank for a grammar point
    review      launch the review web app (localhost)
    flags       review learner problem reports exported from the app
    prompts     compile prompts/runtime/*.yaml -> build/prompts.json
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

    for name in (
        "validate",
        "build",
        "generate",
        "generate-audio",
        "generate-images",
        "review",
        "flags",
        "prompts",
        "release",
    ):
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
        "--coverage",
        action="store_true",
        help="check the closure contract: every A0-A2 grammar point, "
        "function, can-do and lemma introduced by exactly one lesson and "
        "revisited at least twice more, at rising demand",
    )
    val.add_argument(
        "--include-draft",
        action="store_true",
        help="count draft items as supply in --coverage (dev packs)",
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
    flags_cmd = sub.choices["flags"]
    flags_cmd.add_argument("file", help="maestro-flags.jsonl exported from the app")
    flags_cmd.add_argument(
        "--apply",
        action="store_true",
        help="mark the reported items status: flagged (they stop building "
        "until someone clears them) — off by default",
    )
    flags_cmd.add_argument(
        "--json", action="store_true", help="machine-readable output"
    )
    sub.choices["prompts"].add_argument("--out", default="build/prompts.json")
    sub.choices["build"].add_argument("--out", default="build/it.pack.sqlite")
    sub.choices["build"].add_argument(
        "--include-draft",
        action="store_true",
        help="also compile status: draft items (local dev packs only — "
        "`release` always builds reviewed-only)",
    )
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
    aud = sub.choices["generate-audio"]
    aud.add_argument("--provider", default="mock", choices=("mock", "azure", "openai"))
    aud.add_argument("--force", action="store_true", help="re-render everything")
    aud.add_argument("--voice-a", default=None, help="override primary voice")
    aud.add_argument("--voice-b", default=None, help="override secondary voice")
    img = sub.choices["generate-images"]
    img.add_argument("--provider", default="mock", choices=("mock", "openai"))
    img.add_argument("--force", action="store_true", help="re-generate everything")
    img.add_argument(
        "--targets",
        default="scenarios,vocab,readings,lessons,writing,speaking",
        help="comma list of scenarios,vocab,readings,lessons,writing,speaking",
    )
    sub.choices["review"].add_argument("--port", type=int, default=8321)
    rel = sub.choices["release"]
    rel.add_argument("--force", action="store_true", help="replace an existing version")
    rel.add_argument(
        "action",
        nargs="?",
        default="cut",
        choices=("cut", "keygen", "verify", "diff"),
        help="cut (default) | keygen | verify <dir via --dir> | diff",
    )
    rel.add_argument("--dir", type=Path, default=None, help="release dir for verify")

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
        n_uncovered = 0
        if args.coverage:
            from authoring.coverage import (
                check_coverage,
                format_report,
                load_proper_nouns,
            )

            statuses = (
                frozenset({"reviewed", "draft"})
                if args.include_draft
                else frozenset({"reviewed"})
            )
            report = check_coverage(
                spec,
                sources.all_items(),
                statuses=statuses,
                proper_nouns=load_proper_nouns(spec_dir),
            )
            print(format_report(report))
            n_uncovered = len(report.findings)
        for e in errors:
            print(f"ERROR: {e}")
        print(f"{len(errors)} errors, {len(warnings) + n_quality} warnings")
        # Coverage gaps fail the run: the contract is the definition of a
        # finished curriculum, so "not yet" has to be visible in CI.
        return 1 if errors or n_uncovered else 0

    if args.command == "prompts":
        from authoring.prompts import build_prompts

        return build_prompts(Path(args.out))

    if args.command == "flags":
        import json as _json

        from authoring.flags import (
            FlagFileError,
            apply_flags,
            format_report,
            load_flags,
            resolve,
        )

        try:
            reports = load_flags(Path(args.file))
        except (FlagFileError, OSError) as exc:
            print(f"ERROR: {exc}")
            return 1
        resolved = resolve(reports, pack_dir)

        if args.json:
            print(
                _json.dumps(
                    [
                        {
                            "item_id": r.item_id,
                            "status": r.status,
                            "source": str(r.path) if r.path else None,
                            "parent_id": r.parent_id,
                            "notes": [f.note for f in r.flags],
                        }
                        for r in resolved
                    ],
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print(format_report(resolved), end="")

        if args.apply:
            changed = apply_flags(resolved)
            print(
                f"\nmarked {len(changed)} item(s) status: flagged — they will "
                "not build until reviewed"
            )
            for item_id in changed:
                print(f"  {item_id}")
        return 0

    if args.command == "build":
        from authoring.build_pack import build

        return build(
            pack_dir, spec_dir, Path(args.out), include_draft=args.include_draft
        )

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

    if args.command == "generate-audio":
        from authoring.audio import generate_audio

        voices = None
        if args.voice_a and args.voice_b:
            voices = (args.voice_a, args.voice_b)
        generate_audio(pack_dir, args.provider, force=args.force, voices=voices)
        return 0

    if args.command == "generate-images":
        from authoring.images import generate_images

        generate_images(
            pack_dir,
            spec_dir,
            args.provider,
            targets=set(args.targets.split(",")),
            force=args.force,
        )
        return 0

    if args.command == "review":
        import uvicorn

        from authoring.review import create_app

        uvicorn.run(create_app(pack_dir, spec_dir), port=args.port)
        return 0

    if args.command == "release":
        from authoring import release as rel

        if args.action == "keygen":
            rel.keygen()
            return 0
        if args.action == "verify":
            if not args.dir:
                print("verify needs --dir build/release/<version>")
                return 2
            return rel.verify_release(args.dir)
        if args.action == "diff":
            released = rel.latest_release(Path("build/release"), lang)
            if released is None:
                print("no previous release to diff against")
                return 0
            diff = rel.release_diff(pack_dir, spec_dir, released)
            for section, ids in diff.items():
                print(f"{section} ({len(ids)}):")
                for i in ids:
                    print(f"  {i}")
            return 0
        return rel.release(pack_dir, spec_dir, Path("build/release"), force=args.force)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
