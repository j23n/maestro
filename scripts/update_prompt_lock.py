#!/usr/bin/env python3
"""Regenerate prompts/versions.lock after intentionally bumping a prompt version.

Usage: uv run python scripts/update_prompt_lock.py
"""

import hashlib
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = REPO_ROOT / "prompts"
LOCK_FILE = PROMPTS_DIR / "versions.lock"


def compute_lock() -> dict:
    """Read all YAML files in prompts dir, compute sha256 and version for each."""
    result = {}
    for path in sorted(PROMPTS_DIR.glob("*.yaml")):
        content = path.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        data = yaml.safe_load(path.read_text())
        version = str(data.get("version", "1"))
        result[path.name] = {"version": version, "sha256": sha}
    return result


def main() -> None:
    new_lock = compute_lock()

    # Load previous lock if it exists
    old_lock: dict = {}
    if LOCK_FILE.exists():
        try:
            old_lock = json.loads(LOCK_FILE.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: could not read existing lock file: {exc}", file=sys.stderr)

    # Report changes
    all_names = sorted(set(old_lock) | set(new_lock))
    changed = False
    for name in all_names:
        old_entry = old_lock.get(name)
        new_entry = new_lock.get(name)
        if old_entry is None:
            print(f"  + {name}: added (version={new_entry['version']})")
            changed = True
        elif new_entry is None:
            print(f"  - {name}: removed")
            changed = True
        elif old_entry["sha256"] != new_entry["sha256"]:
            if old_entry["version"] != new_entry["version"]:
                print(
                    f"  ~ {name}: content changed, version bumped "
                    f"{old_entry['version']} -> {new_entry['version']}"
                )
            else:
                print(
                    f"  ~ {name}: content changed but version unchanged "
                    f"(still {new_entry['version']}) — did you forget to bump?"
                )
            changed = True
        elif old_entry["version"] != new_entry["version"]:
            print(
                f"  ~ {name}: version changed "
                f"{old_entry['version']} -> {new_entry['version']} (content unchanged)"
            )
            changed = True
        else:
            print(f"  . {name}: unchanged (version={new_entry['version']})")

    if not changed:
        print("\nNo changes — lock file is already up to date.")
        return

    LOCK_FILE.write_text(json.dumps(new_lock, indent=2) + "\n")
    print(f"\nLock file written: {LOCK_FILE}")


if __name__ == "__main__":
    main()
