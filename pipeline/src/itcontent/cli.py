"""The `content` CLI (docs/04 § Commands). Each command lives in its own module; this file only wires them up."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from itcontent import __version__

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Italiano content pipeline (docs/04): lint, annotate, check, tts, build, review loop, reports.",
)


@app.callback()
def _main() -> None:
    """Italiano content pipeline."""


@app.command()
def version() -> None:
    """Print the pipeline version."""
    typer.echo(__version__)


@app.command()
def lint(
    as_json: bool = typer.Option(False, "--json", help="Print the findings as JSON instead of one line each."),
) -> None:
    """YAML parse, JSON Schemas, ID formats, references, approval hashes, review ledgers."""
    from itcontent.lint import run_lint

    sys.exit(run_lint(echo=typer.echo, as_json=as_json))


def _ask(prompt: str) -> str:
    return typer.prompt(prompt, default="", show_default=False)


@app.command()
def approve(
    file: Annotated[Path, typer.Argument(help="The content file, e.g. content/units/02-al-bar/lesson-1.yaml.")],
    by: Annotated[str, typer.Option("--by", help="The content lead's name.")],
    signoff: Annotated[
        Path | None, typer.Option("--signoff", help="The teacher's signed review file (task M1.13).")
    ] = None,
) -> None:
    """Humans only: mark a file approved (status, by, date, approval hash). Refuses in an agent's shell (ADR-15)."""
    from itcontent.approval import approve as run

    sys.exit(run(file, by, signoff=signoff, ask=_ask, echo=typer.echo))


@app.command()
def reopen(
    file: Annotated[Path, typer.Argument(help="The approved content file to reopen.")],
) -> None:
    """Humans only: set a file back to in-review and clear by, date and hash. Refuses in an agent's shell."""
    from itcontent.approval import reopen as run

    sys.exit(run(file, ask=_ask, echo=typer.echo))


@app.command()
def annotate(
    check: bool = typer.Option(False, "--check", help="regenerate in memory and fail on stale lock files"),
) -> None:
    """Tokenise and annotate every Italian string; write content/.annotations/**.json (docs/04 § Annotation)."""
    from itcontent.annotate import run_annotate

    sys.exit(run_annotate(check=check))


@app.command()
def check(
    unit: str = typer.Option(None, "--unit", help="report only findings about this unit (e.g. u02)"),
    as_json: bool = typer.Option(False, "--json", help="print the report as JSON instead of one line per finding"),
) -> None:
    """Checks 1–5 (docs/04 § The ten quality checks); writes build/reports/check.{json,md}. Fails on any error."""
    from itcontent.checks import run_check

    sys.exit(run_check(unit=unit, as_json=as_json, echo=typer.echo))


@app.command()
def report(
    unit: str = typer.Option(None, "--unit", help="only this unit (e.g. u02), or the review scopes specs, assessments"),
) -> None:
    """Content dashboard: new words, encounters, strands, coverage, budgets, open review comments."""
    from itcontent.report import run_report

    sys.exit(run_report(unit=unit, echo=typer.echo))


@app.command()
def freq(
    words: list[str] = typer.Argument(..., help="Italian words (forms or lemmas)"),
    freq_file: Path = typer.Option(None, "--freq", help="frequency list (default pipeline/data/frequency/it_50k.txt)"),
) -> None:
    """Frequency ranks of words and their lemmas, and the items that cover them (docs/04)."""
    from itcontent.freq import run_freq

    sys.exit(run_freq(words, freq_file=freq_file, echo=typer.echo))


@app.command()
def suggest(
    unit: str = typer.Option(..., "--unit", help="the unit the items are for (e.g. u07)"),
    topic: str = typer.Option(None, "--topic", help="show the items this topic already has (e.g. topic:food-drink)"),
    pos: str = typer.Option(None, "--pos", help="only this part of speech (noun, verb, adj, adv, …)"),
    word: list[str] = typer.Option(None, "--word", help="rank only these words (repeatable): your list for the topic"),
    limit: int = typer.Option(40, "--limit", help="how many candidates"),
    freq_file: Path = typer.Option(None, "--freq", help="frequency list (default pipeline/data/frequency/it_50k.txt)"),
) -> None:
    """High-frequency lemmas no item covers yet, for drafting a unit's item graph (docs/04)."""
    from itcontent.freq import run_suggest

    sys.exit(
        run_suggest(
            unit=unit, topic=topic, pos=pos, words=word or None, limit=limit, freq_file=freq_file, echo=typer.echo
        )
    )


@app.command("beta-import")
def beta_import(
    events: Path = typer.Argument(..., exists=True, dir_okay=False, help="JSONL export from the study endpoint"),
    out: Path = typer.Option(None, help="output folder (default build/reports/beta)"),
) -> None:
    """Item statistics and rejected typed answers from study telemetry (docs/04, docs/12)."""
    from itcontent import paths
    from itcontent.beta import run_beta_import

    target = out or (paths.REPORTS / "beta")
    report = run_beta_import(events, target)
    typer.echo(f"{report.events} events from {report.learners} learners → {target}")


@app.command()
def build(
    release: bool = typer.Option(False, "--release", help="only approved content; missing audio fails"),
    allow_partial: bool = typer.Option(False, "--allow-partial", help="release: ship the approved prefix of units"),
    mini: bool = typer.Option(False, "--mini", help="fixtures/packs/mini.sqlite and mini-payloads.json"),
    out: Path = typer.Option(None, "--out", help="where to write the pack (default by mode, docs/04)"),
) -> None:
    """Compile the content pack (docs/04 § Pack build); dev builds include drafts and warn on missing audio."""
    from itcontent.pack.build import run_build

    if release and mini:
        typer.echo("error: --release and --mini don't combine")
        sys.exit(2)
    mode = "release" if release else ("mini" if mini else "dev")
    sys.exit(run_build(mode=mode, allow_partial=allow_partial, out=out, echo=typer.echo))


@app.command("pack-hash")
def pack_hash(
    pack: Path = typer.Option(None, "--pack", help="default: App/Italiano/Resources/Content/content.sqlite"),
) -> None:
    """Print the canonical pack hash (meta content_hash, git_sha and built_with excluded)."""
    from itcontent.pack.build import run_pack_hash

    sys.exit(run_pack_hash(pack, echo=typer.echo))


@app.command("review-export")
def review_export(
    specs: bool = typer.Option(False, "--specs", help="The sign-off files: syllabus, unit specs, points, story bible…"),
    unit: str = typer.Option(None, "--unit", help="A unit's items, lessons, task and check, e.g. u02."),
    assessments: bool = typer.Option(False, "--assessments", help="The placement test and the final A1 check."),
    since: bool = typer.Option(False, "--since", help="Show earlier comments' resolutions and mark what changed."),
    rejected: Path = typer.Option(
        None, help="Beta rejected answers to adjudicate (default build/reports/beta/rejected.json, if present)."
    ),
    out: Path = typer.Option(None, help="Output file (default build/review/<scope>/index.html)."),
) -> None:
    """The teacher's review page: one self-contained HTML file (docs/04 § Content review loop)."""
    import re

    from itcontent import paths
    from itcontent.review_export import export

    chosen = [s for s, on in (("specs", specs), (unit, unit is not None), ("assessments", assessments)) if on]
    if len(chosen) != 1:
        typer.echo("choose one of --specs, --unit uNN, --assessments")
        sys.exit(2)
    scope = str(chosen[0])
    if scope not in ("specs", "assessments") and not re.fullmatch(r"u\d{2}", scope):
        typer.echo(f"--unit takes a unit ID like u02, not '{scope}'")
        sys.exit(2)
    default_rejected = paths.REPORTS / "beta" / "rejected.json"
    try:
        result = export(
            scope, since=since, rejected=rejected or (default_rejected if default_rejected.is_file() else None), out=out
        )
    except ValueError as exc:
        typer.echo(str(exc))
        sys.exit(1)
    typer.echo(result.summary(paths.ROOT))


@app.command("review-import")
def review_import(
    review: Path = typer.Argument(..., help="The review file (review-<scope>-<date>.json) from a page or the app."),
) -> None:
    """File a review in reviews/inbox/, add its comments to the ledger reviews/<scope>.yaml, print the worklist."""
    from itcontent.review_import import run

    sys.exit(run(review, echo=typer.echo))


if __name__ == "__main__":
    app()
