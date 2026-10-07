"""The `content` CLI (docs/04 § Commands). Each command lives in its own module; this file only wires them up."""

from __future__ import annotations

import sys

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


if __name__ == "__main__":
    app()
