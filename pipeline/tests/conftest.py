"""Shared pytest fixtures. Tests never use the network (docs/04, .claude/rules/pipeline.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from itcontent import paths

DATA_MISSING = not (paths.DATA / "morph-it" / "morph-it.txt").is_file()
needs_data = pytest.mark.skipif(DATA_MISSING, reason="pipeline/data is missing: run `make data`")


@pytest.fixture(scope="session")
def root() -> Path:
    return paths.ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
