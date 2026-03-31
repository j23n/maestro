#!/usr/bin/env python3
"""Recompute dwds_headwords.lock from dwds_headwords.json.

The lock file stores the SHA256 hash of dwds_headwords.json and is committed to the repo.
At app startup, dwds_sync compares this hash against what's stored in the database and
runs headword ingest if they differ — ensuring the DB always matches the committed JSON.

Usage: uv run python scripts/update_dwds_lock.py
"""

import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "de"
HEADWORDS_FILE = DATA_DIR / "dwds_headwords.json"
LOCK_FILE = DATA_DIR / "dwds_headwords.lock"

_SUPERSCRIPT_RE = re.compile(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+$")


def main() -> None:
    if not HEADWORDS_FILE.exists():
        print(f"ERROR: {HEADWORDS_FILE} not found", file=sys.stderr)
        sys.exit(1)

    content = HEADWORDS_FILE.read_bytes()
    sha = hashlib.sha256(content).hexdigest()

    # Count valid headwords for metadata
    raw: dict[str, str] = json.loads(content)
    seen: set[str] = set()
    for headword in raw:
        stripped = headword.strip()
        if not stripped or stripped.startswith("-") or not stripped[0].isalpha():
            continue
        stripped = _SUPERSCRIPT_RE.sub("", stripped)
        stripped = unicodedata.normalize("NFC", stripped)
        if stripped:
            seen.add(stripped)

    old_sha = None
    if LOCK_FILE.exists():
        try:
            old_sha = json.loads(LOCK_FILE.read_text())["sha256"]
        except Exception:
            pass

    lock = {
        "sha256": sha,
        "headword_count": len(seen),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    LOCK_FILE.write_text(json.dumps(lock, indent=2) + "\n")

    if old_sha is None:
        print(f"  [de] + dwds_headwords.lock: created (headwords={len(seen)})")
    elif old_sha != sha:
        print(f"  [de] ~ dwds_headwords.json: hash changed (headwords={len(seen)})")
    else:
        print(f"  [de] . dwds_headwords.json: unchanged (hash={sha[:16]})")


if __name__ == "__main__":
    main()
