"""Shared pytest fixtures. Tests never use the network (docs/04, .claude/rules/pipeline.md)."""

from __future__ import annotations

import shutil
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


def copy_course(root: Path, dst: Path) -> Path:
    """A throwaway repository with the seed `content/` (and `reviews/` if present): tests edit copies, never seeds."""
    shutil.copytree(root / "content", dst / "content", ignore=shutil.ignore_patterns(".annotations"))
    if (root / "reviews").is_dir():
        shutil.copytree(root / "reviews", dst / "reviews")
    return dst


@pytest.fixture
def course_copy(root: Path, tmp_path: Path) -> Path:
    return copy_course(root, tmp_path / "repo")


@pytest.fixture
def place(course_copy: Path, fixtures_dir: Path):
    """place(fixture, target): copy fixtures/invalid/<fixture> to <target> in the course copy; returns its path."""

    def _place(fixture: str, target: str) -> Path:
        dst = course_copy / target
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixtures_dir / "invalid" / fixture, dst)
        return dst

    return _place
