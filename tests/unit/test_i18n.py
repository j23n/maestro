"""Unit tests for i18n helpers."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from maestro.i18n import _cache, t


@pytest.fixture(autouse=True)
def _clear_i18n_cache():
    _cache.clear()
    yield
    _cache.clear()


@pytest.mark.unit
def test_t_loads_from_ui_language():
    """t() returns English when UI_LANGUAGE='en'."""
    with patch("maestro.i18n.settings") as mock_settings:
        mock_settings.UI_LANGUAGE = "en"
        assert t("nav_lesson") == "Lesson"


@pytest.mark.unit
def test_t_falls_back_to_key():
    """Unknown key returns the key itself."""
    with patch("maestro.i18n.settings") as mock_settings:
        mock_settings.UI_LANGUAGE = "en"
        assert t("nonexistent") == "nonexistent"


@pytest.mark.unit
def test_t_format_kwargs():
    """Placeholder interpolation works."""
    with patch("maestro.i18n.settings") as mock_settings:
        mock_settings.UI_LANGUAGE = "en"
        result = t("progress_label", current=2, total=5)
        assert result == "Activity 2 of 5"


@pytest.mark.unit
def test_t_italian_ui():
    """t() returns Italian when UI_LANGUAGE='it'."""
    with patch("maestro.i18n.settings") as mock_settings:
        mock_settings.UI_LANGUAGE = "it"
        assert t("nav_lesson") == "Lezione"


@pytest.mark.unit
def test_en_json_keys_match_it_json():
    """en.json and it.json must have exactly the same keys."""
    root = Path(__file__).resolve().parents[2] / "src" / "maestro" / "i18n"
    with open(root / "en.json") as f:
        en_keys = set(json.load(f).keys())
    with open(root / "it.json") as f:
        it_keys = set(json.load(f).keys())
    assert en_keys == it_keys, (
        f"Missing in en: {it_keys - en_keys}; missing in it: {en_keys - it_keys}"
    )


@pytest.mark.unit
def test_strings_t_english():
    """strings.t() returns English when UI_LANGUAGE='en'."""
    from maestro import strings

    with patch("maestro.strings.settings") as mock_settings:
        mock_settings.UI_LANGUAGE = "en"
        result = strings.t("grammar_title", label="X")
        assert result == "Grammar: X"
