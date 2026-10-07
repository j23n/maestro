"""The `content` CLI (docs/04 § Commands). Each command lives in its own module; this file only wires them up."""

from __future__ import annotations

import sys
from pathlib import Path

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
def lint() -> None:
    """YAML parse, JSON Schemas, ID formats, references, approval hashes, review ledgers."""
    from itcontent.lint import run_lint

    sys.exit(run_lint())


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
