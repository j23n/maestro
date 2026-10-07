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


if __name__ == "__main__":
    app()
