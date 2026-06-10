"""Validate the checked-in content bank files (schema + cross-references).

Runs the bank lint over every language/level bank present in data/.
Coverage gaps are allowed (the planner falls back to LLM generation);
schema errors, unknown codes, and empty prompts/answers are not.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from maestro.utils import data_dir, iter_language_dirs

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_lint():
    spec = importlib.util.spec_from_file_location(
        "bank_lint", _REPO_ROOT / "scripts" / "bank_lint.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _banks_present() -> list[tuple[str, str]]:
    found = []
    for lang_dir in iter_language_dirs():
        banks = data_dir(lang_dir.name) / "banks"
        if banks.is_dir():
            for level_dir in sorted(banks.iterdir()):
                if level_dir.is_dir():
                    found.append((lang_dir.name, level_dir.name.upper()))
    return found


def test_bank_files_have_no_lint_errors():
    banks = _banks_present()
    assert banks, "expected at least one content bank in data/"
    lint = _load_lint()
    all_errors = []
    for lang, level in banks:
        errors, _warnings = lint.lint(lang, level)
        all_errors.extend(f"[{lang}/{level}] {e}" for e in errors)
    assert not all_errors, "\n".join(all_errors)


def test_seed_bank_loads_through_loader():
    """The runtime loader must parse every seed file (it skips invalid ones,
    so compare counts against the raw files on disk)."""
    from maestro.lessons import bank

    bank.invalidate()
    try:
        for lang, level in _banks_present():
            root = bank.bank_dir(lang, level)
            drills = bank.load_drill_bank(lang, level)
            assert len(drills) == len(list((root / "drills").glob("*.yaml")))
            texts = bank.load_text_bank(lang, level)
            assert len(texts) == len(list((root / "texts").glob("*.yaml")))
            for gp_code, drill_file in drills.items():
                assert gp_code == drill_file.grammar_point_code
                assert len(drill_file.items) >= 6
    finally:
        bank.invalidate()
