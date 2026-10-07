"""Repository paths. The repo root is found from this file, or from ITALIANO_ROOT (tests and worktrees)."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    env = os.environ.get("ITALIANO_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "content" / "course.yaml").is_file() and (parent / "pipeline").is_dir():
            return parent
    return Path.cwd().resolve()


ROOT = repo_root()
CONTENT = ROOT / "content"
SCHEMAS = ROOT / "schemas"
FIXTURES = ROOT / "fixtures"
PIPELINE = ROOT / "pipeline"
DATA = PIPELINE / "data"
BUILD = ROOT / "build"
REPORTS = BUILD / "reports"
REVIEWS = ROOT / "reviews"
PACK_SQL = SCHEMAS / "content-pack.sql"
APP_CONTENT = ROOT / "App" / "Italiano" / "Resources" / "Content"
