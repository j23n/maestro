"""Unit test: verify data files match their lock files.

If vocab_a0.yaml, grammar_points.yaml, comm_functions.json, or
a0_lessons.yaml/scenarios_a0.yaml content has changed but the corresponding
lock file was not updated, this test fails with a clear message explaining
how to fix the problem.

Tests are parametrized over all language directories under data/.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

from maestro.utils import DATA_DIR_ROOT

# Discover all languages that have data directories
_LANG_DIRS = sorted(
    d
    for d in DATA_DIR_ROOT.iterdir()
    if d.is_dir() and d.name not in ("seed", "images")
)
_LANG_IDS = [d.name for d in _LANG_DIRS]

DE_DATA_DIR = DATA_DIR_ROOT / "de"


@pytest.fixture(params=_LANG_DIRS, ids=_LANG_IDS)
def lang_dir(request):
    return request.param


@pytest.mark.unit
@pytest.mark.parametrize(
    "data_file, lock_file, update_script",
    [
        ("vocab_a0.yaml", "vocab_a0.lock", "scripts/update_vocab_lock.py"),
        ("grammar_points.yaml", "grammar_points.lock", "scripts/update_gp_lock.py"),
        ("comm_functions.json", "comm_functions.lock", "scripts/update_cf_lock.py"),
    ],
)
def test_data_file_matches_lock(lang_dir, data_file, lock_file, update_script):
    data_path = lang_dir / data_file
    lock_path = lang_dir / lock_file

    if not data_path.exists():
        pytest.skip(f"[{lang_dir.name}] {data_file} not found")

    if not lock_path.exists():
        pytest.fail(
            f"[{lang_dir.name}] {lock_file} not found. Run: uv run python {update_script}"
        )

    try:
        lock_data = json.loads(lock_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        pytest.fail(f"[{lang_dir.name}] Could not read {lock_file}: {exc}")

    actual_sha = hashlib.sha256(data_path.read_bytes()).hexdigest()
    locked_sha = lock_data.get("sha256", "")

    if actual_sha != locked_sha:
        pytest.fail(
            f"[{lang_dir.name}] {data_file} content changed but {lock_file} was not updated. "
            f"Run: uv run python {update_script}"
        )


@pytest.mark.unit
def test_a0_lessons_lock(lang_dir):
    """Verify a0_lessons.yaml + scenarios_a0.yaml match a0_lessons.lock."""
    lessons_path = lang_dir / "a0_lessons.yaml"
    scenarios_path = lang_dir / "scenarios_a0.yaml"
    lock_path = lang_dir / "a0_lessons.lock"
    update_script = "scripts/update_a0_lessons_lock.py"

    if not lessons_path.exists():
        pytest.skip(f"[{lang_dir.name}] a0_lessons.yaml not found")
    if not scenarios_path.exists():
        pytest.skip(f"[{lang_dir.name}] scenarios_a0.yaml not found")

    if not lock_path.exists():
        pytest.fail(
            f"[{lang_dir.name}] a0_lessons.lock not found. "
            f"Run: uv run python {update_script} --lang {lang_dir.name}"
        )

    try:
        lock_data = json.loads(lock_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        pytest.fail(f"[{lang_dir.name}] Could not read a0_lessons.lock: {exc}")

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
            f"[{lang_dir.name}] a0_lessons.yaml or scenarios_a0.yaml changed but "
            f"a0_lessons.lock was not updated. "
            f"Run: uv run python {update_script} --lang {lang_dir.name}"
        )


@pytest.mark.unit
def test_a0_lesson_slug_alignment(lang_dir):
    """Every scenario slug must have a matching key in a0_lessons.yaml."""
    lessons_path = lang_dir / "a0_lessons.yaml"
    scenarios_path = lang_dir / "scenarios_a0.yaml"

    if not lessons_path.exists() or not scenarios_path.exists():
        pytest.skip(f"[{lang_dir.name}] a0_lessons.yaml or scenarios_a0.yaml not found")

    with open(lessons_path) as f:
        lessons_data = yaml.safe_load(f)
    with open(scenarios_path) as f:
        scenarios_data = yaml.safe_load(f)

    lesson_keys = set(lessons_data.keys()) if lessons_data else set()
    scenario_slugs = [s["slug"] for s in (scenarios_data or {}).get("scenarios", [])]
    missing = [slug for slug in scenario_slugs if slug not in lesson_keys]

    if missing:
        pytest.fail(
            f"[{lang_dir.name}] Scenario slugs with no matching lesson in a0_lessons.yaml: {missing}. "
            f"Either update the YAML keys or scenarios_a0.yaml slugs to match."
        )


def test_dwds_headwords_lock():
    """Verify dwds_headwords.json matches dwds_headwords.lock."""
    data_path = DE_DATA_DIR / "dwds_headwords.json"
    lock_path = DE_DATA_DIR / "dwds_headwords.lock"
    update_script = "scripts/update_dwds_lock.py"

    if not data_path.exists():
        pytest.skip("dwds_headwords.json not found")

    if not lock_path.exists():
        pytest.fail(
            f"dwds_headwords.lock not found. Run: uv run python {update_script}"
        )

    try:
        lock_data = json.loads(lock_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        pytest.fail(f"Could not read dwds_headwords.lock: {exc}")

    actual_sha = hashlib.sha256(data_path.read_bytes()).hexdigest()
    locked_sha = lock_data.get("sha256", "")

    if actual_sha != locked_sha:
        pytest.fail(
            f"dwds_headwords.json content changed but dwds_headwords.lock was not updated. "
            f"Run: uv run python {update_script}"
        )
