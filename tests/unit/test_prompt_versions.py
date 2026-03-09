"""Unit test: verify prompt files match prompts/versions.lock.

If a prompt's content has changed but the lock file was not updated, this test
fails with a clear message explaining how to fix the problem.
"""

import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = REPO_ROOT / "prompts"
LOCK_FILE = PROMPTS_DIR / "versions.lock"


def test_prompt_versions_match_lock():
    """All prompt YAML files must match the sha256 recorded in versions.lock."""
    if not LOCK_FILE.exists():
        pytest.fail(
            "prompts/versions.lock not found. "
            "Run scripts/update_prompt_lock.py to generate it."
        )

    try:
        lock_data = json.loads(LOCK_FILE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        pytest.fail(f"Could not read prompts/versions.lock: {exc}")

    yaml_files = sorted(PROMPTS_DIR.glob("*.yaml"))
    assert yaml_files, f"No YAML files found in {PROMPTS_DIR}"

    failures = []
    for path in yaml_files:
        name = path.name
        content = path.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest()

        if name not in lock_data:
            failures.append(
                f"prompts/{name} is not in versions.lock. "
                f"Run scripts/update_prompt_lock.py after bumping version: in the YAML."
            )
            continue

        locked_sha = lock_data[name].get("sha256", "")
        if actual_sha != locked_sha:
            failures.append(
                f"prompts/{name} content changed but version was not bumped. "
                f"Run scripts/update_prompt_lock.py after bumping version: in the YAML."
            )

    if failures:
        pytest.fail("\n".join(failures))
