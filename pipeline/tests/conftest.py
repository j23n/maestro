"""Shared pytest fixtures. Tests never use the network (docs/04).

Two courses (docs/10 § Test layers):

- the **seed course** (`fixtures/seed-course/`, frozen): `content/` as it was with only the golden Unit 2 Lesson 1
  written. Tests that pin facts about the course (counts, step tables, line numbers, report rows) run on it, through
  `seed_root` (read-only) or `course_copy` (a throwaway copy to edit), so they don't break whenever a lesson is added;
- the **live course** (`root`, the repository's `content/`): only tests about the live course itself use it (it
  lints, its lock files are fresh, its review pages resolve, its packs build deterministically).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from itcontent import paths
from itcontent.pack.build import SEED_COURSE

DATA_MISSING = not (paths.DATA / "morph-it" / "morph-it.txt").is_file()
needs_data = pytest.mark.skipif(DATA_MISSING, reason="pipeline/data is missing: run `make data`")
SEED = paths.ROOT / SEED_COURSE


@pytest.fixture(scope="session")
def root() -> Path:
    """The repository, with the live course."""
    return paths.ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


def copy_course(root: Path, dst: Path) -> Path:
    """A throwaway repository with the `content/` of `root` (lock files included, so `content check` works on it),
    `reviews/` if present, and Morph-it! linked in (so `content annotate` works): tests edit copies, never seeds."""
    shutil.copytree(root / "content", dst / "content")
    if (root / "reviews").is_dir():
        shutil.copytree(root / "reviews", dst / "reviews")
    (dst / "pipeline" / "data").mkdir(parents=True)
    (dst / "pipeline" / "data" / "morph-it").symlink_to(paths.DATA / "morph-it")
    return dst


def copy_seed(dst: Path) -> Path:
    """A throwaway repository holding the frozen seed course."""
    return copy_course(SEED, dst)


@pytest.fixture(scope="session")
def seed_root(tmp_path_factory) -> Path:
    """The frozen seed course as a repository (one copy per session: read it, never edit it)."""
    return copy_seed(tmp_path_factory.mktemp("seed") / "repo")


@pytest.fixture
def course_copy(tmp_path: Path) -> Path:
    """A fresh copy of the seed course to edit."""
    return copy_seed(tmp_path / "repo")


@pytest.fixture
def place(course_copy: Path, fixtures_dir: Path):
    """place(fixture, target): copy fixtures/invalid/<fixture> to <target> in the course copy; returns its path."""

    def _place(fixture: str, target: str) -> Path:
        dst = course_copy / target
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixtures_dir / "invalid" / fixture, dst)
        return dst

    return _place
