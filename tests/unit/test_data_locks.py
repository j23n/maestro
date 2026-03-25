"""Unit test: verify data files match their lock files.

If vocab_a0.yaml, grammar_points.yaml, or a0_lessons.yaml/scenarios_a0.yaml
content has changed but the corresponding lock file was not updated, this test
fails with a clear message explaining how to fix the problem.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

DATA_DIR = Path(__file__).resolve().parents[2] / "src" / "maestro" / "data" / "it"


@pytest.mark.parametrize(
    "data_file, lock_file, update_script",
    [
        ("vocab_a0.yaml", "vocab_a0.lock", "scripts/update_vocab_lock.py"),
        ("grammar_points.yaml", "grammar_points.lock", "scripts/update_gp_lock.py"),
        ("comm_functions.json", "comm_functions.lock", "scripts/update_cf_lock.py"),
    ],
)
def test_data_file_matches_lock(data_file, lock_file, update_script):
    data_path = DATA_DIR / data_file
    lock_path = DATA_DIR / lock_file

    if not data_path.exists():
        pytest.skip(f"{data_file} not found")

    if not lock_path.exists():
        pytest.fail(f"{lock_file} not found. Run: uv run python {update_script}")

    try:
        lock_data = json.loads(lock_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        pytest.fail(f"Could not read {lock_file}: {exc}")

    actual_sha = hashlib.sha256(data_path.read_bytes()).hexdigest()
    locked_sha = lock_data.get("sha256", "")

    if actual_sha != locked_sha:
        pytest.fail(
            f"{data_file} content changed but {lock_file} was not updated. "
            f"Run: uv run python {update_script}"
        )


def test_a0_lessons_lock():
    """Verify a0_lessons.yaml + scenarios_a0.yaml match a0_lessons.lock."""
    lessons_path = DATA_DIR / "a0_lessons.yaml"
    scenarios_path = DATA_DIR / "scenarios_a0.yaml"
    lock_path = DATA_DIR / "a0_lessons.lock"
    update_script = "scripts/update_a0_lessons_lock.py"

    if not lessons_path.exists():
        pytest.skip("a0_lessons.yaml not found")
    if not scenarios_path.exists():
        pytest.skip("scenarios_a0.yaml not found")

    if not lock_path.exists():
        pytest.fail(f"a0_lessons.lock not found. Run: uv run python {update_script}")

    try:
        lock_data = json.loads(lock_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        pytest.fail(f"Could not read a0_lessons.lock: {exc}")

    # Import LOCK_VERSION to keep hash in sync with the lock script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from update_a0_lessons_lock import LOCK_VERSION

    h = hashlib.sha256()
    h.update(f"v{LOCK_VERSION}:".encode())
    h.update(lessons_path.read_bytes())
    h.update(scenarios_path.read_bytes())
    actual_sha = h.hexdigest()
    locked_sha = lock_data.get("sha256", "")

    if actual_sha != locked_sha:
        pytest.fail(
            f"a0_lessons.yaml or scenarios_a0.yaml changed but a0_lessons.lock "
            f"was not updated. Run: uv run python {update_script}"
        )


def test_a0_lesson_slug_alignment():
    """Every scenario slug must have a matching key in a0_lessons.yaml."""
    lessons_path = DATA_DIR / "a0_lessons.yaml"
    scenarios_path = DATA_DIR / "scenarios_a0.yaml"

    if not lessons_path.exists() or not scenarios_path.exists():
        pytest.skip("a0_lessons.yaml or scenarios_a0.yaml not found")

    with open(lessons_path) as f:
        lessons_data = yaml.safe_load(f)
    with open(scenarios_path) as f:
        scenarios_data = yaml.safe_load(f)

    lesson_keys = set(lessons_data.keys()) if lessons_data else set()
    scenario_slugs = [s["slug"] for s in (scenarios_data or {}).get("scenarios", [])]
    missing = [slug for slug in scenario_slugs if slug not in lesson_keys]

    if missing:
        pytest.fail(
            f"Scenario slugs with no matching lesson in a0_lessons.yaml: {missing}. "
            f"Either update the YAML keys or scenarios_a0.yaml slugs to match."
        )
