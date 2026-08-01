"""Compile the shared runtime prompts into a bundle the app can read.

``prompts/runtime/*.yaml`` is the single source for the prompts the app
sends and the eval harness measures — that shared source is what makes
"the eval measures what ships" true. The app can't read YAML without
taking a dependency, so the build emits the same content as JSON.

Deliberately a straight transcription: no rewriting, no defaults applied.
If the two ever diverge the invariant is broken, and
``tests/unit/test_prompts.py`` fails.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

RUNTIME_DIR = Path("prompts/runtime")
TASKS = ("writing_feedback", "speaking_feedback", "mistake_explanation")


def load_prompts(runtime_dir: Path = RUNTIME_DIR) -> dict[str, dict]:
    """Every runtime prompt, keyed by task."""
    prompts: dict[str, dict] = {}
    for path in sorted(runtime_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        task = data.get("task")
        if not task:
            raise ValueError(f"{path}: prompt has no `task`")
        if task in prompts:
            raise ValueError(f"{path}: duplicate task {task}")
        for required in ("version", "system", "template"):
            if required not in data:
                raise ValueError(f"{path}: prompt is missing `{required}`")
        prompts[task] = {
            "version": data["version"],
            "system": data["system"],
            "template": data["template"],
            "defaults": data.get("defaults") or {},
        }
    return prompts


def build_prompts(out_path: Path, runtime_dir: Path = RUNTIME_DIR) -> int:
    prompts = load_prompts(runtime_dir)
    missing = [t for t in TASKS if t not in prompts]
    if missing:
        print(f"ERROR: no runtime prompt for {', '.join(missing)}")
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(prompts, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    versions = ", ".join(f"{t} v{p['version']}" for t, p in sorted(prompts.items()))
    print(f"built {out_path}: {len(prompts)} prompts ({versions})")
    return 0
