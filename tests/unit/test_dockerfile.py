"""Verify the Dockerfile copies all runtime-relevant repo directories.

When a new top-level directory is added that the app needs at runtime,
this test fails if the Dockerfile doesn't COPY it — catching the class
of bug where files exist in the repo but are missing from the container
(e.g. the data/ directory was missing, causing FileNotFoundError on prod).
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

# Top-level directories that are intentionally NOT in the Docker image
# and NOT in .dockerignore.  Prefer adding dirs to .dockerignore instead;
# this set is a fallback for dirs that must stay in the build context.
_DEV_ONLY_DIRS: set[str] = set()


def _parse_dockerignore_dirs() -> set[str]:
    """Top-level names excluded by .dockerignore.

    NOTE: This is a simplified parser — it treats each line as a literal
    top-level name.  It does not handle negation (``!``), globs with path
    separators, or ``**`` patterns.  That's fine for the current file; if
    .dockerignore grows more complex, this function will need updating.
    """
    if not DOCKERIGNORE.exists():
        return set()
    return {
        line.strip().rstrip("/")
        for line in DOCKERIGNORE.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def _parse_copy_sources() -> set[str]:
    """Source names from COPY instructions in the Dockerfile."""
    sources = set()
    for line in DOCKERFILE.read_text().splitlines():
        if not line.startswith("COPY") or "--from=" in line:
            continue
        parts = line.split()
        paths = [p for p in parts[1:] if not p.startswith("--")]
        # Last element is the destination; the rest are sources
        for src in paths[:-1]:
            sources.add(src.rstrip("/"))
    return sources


@pytest.mark.unit
def test_dockerfile_copies_all_runtime_dirs():
    """Every top-level repo dir is either COPY'd, .dockerignored, or dev-only."""
    repo_dirs = {
        p.name for p in REPO_ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")
    }

    accounted_for = _parse_copy_sources() | _parse_dockerignore_dirs() | _DEV_ONLY_DIRS
    missing = repo_dirs - accounted_for

    assert not missing, (
        f"Top-level repo directories not accounted for in Docker image: {missing}. "
        f"If the app needs them at runtime, add 'COPY <dir>/ /app/<dir>/' to the Dockerfile. "
        f"If they are dev-only, add them to .dockerignore or _DEV_ONLY_DIRS in {Path(__file__).name}."
    )
