"""Internationalisation helpers for Jinja2 templates.

Usage (in Python):
    from maestro.i18n import t as i18n_t
    templates.env.globals["t"] = i18n_t

Usage (in templates):
    {{ t("nav_lesson") }}
    {{ t("vocab_italian_word", language=target_language) }}
"""

import json
from pathlib import Path

from maestro.config import settings

_ROOT = Path(__file__).parent
_cache: dict[str, dict] = {}


def _load(lang: str) -> dict:
    if lang not in _cache:
        with open(_ROOT / f"{lang}.json") as f:
            _cache[lang] = json.load(f)
    return _cache[lang]


def t(key: str, **kwargs) -> str:
    """Look up a template-facing string by key and format with kwargs."""
    strings = _load(settings.TARGET_LANGUAGE)
    template = strings.get(key, key)
    return template.format(**kwargs) if kwargs else template
