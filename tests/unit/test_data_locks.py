"""Unit test: verify data files match their lock files.

If vocab_a0.json or grammar_points.yaml content has changed but the
corresponding lock file was not updated, this test fails with a clear
message explaining how to fix the problem.
"""

import hashlib
import json
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parents[2] / "src" / "maestro" / "data" / "it"


@pytest.mark.parametrize(
    "data_file, lock_file, update_script",
    [
        ("vocab_a0.json", "vocab_a0.lock", "scripts/update_vocab_lock.py"),
        ("grammar_points.yaml", "grammar_points.lock", "scripts/update_gp_lock.py"),
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
