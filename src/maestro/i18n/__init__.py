"""Internationalisation helpers.

Two namespaces:
  t()         — template-facing strings loaded from JSON files (en.json, it.json).
  strings_t() — Python-side activity titles/descriptions (inline dict).

Usage (templates):
    from maestro.i18n import t as i18n_t
    templates.env.globals["t"] = i18n_t
    {{ t("nav_lesson") }}

Usage (Python code):
    from maestro.i18n import strings_t
    title = strings_t("grammar_title", label="Present tense")
"""

import json
from pathlib import Path

from maestro.config import settings

# --- Template strings (from JSON) ---

_ROOT = Path(__file__).parent
_cache: dict[str, dict] = {}


def _load(lang: str) -> dict:
    if lang not in _cache:
        with open(_ROOT / f"{lang}.json") as f:
            _cache[lang] = json.load(f)
    return _cache[lang]


def t(key: str, **kwargs) -> str:
    """Look up a template-facing string by key and format with kwargs."""
    strings = _load(settings.UI_LANGUAGE)
    template = strings.get(key, key)
    return template.format(**kwargs) if kwargs else template


# --- Python-side activity title strings (inline) ---

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # materialize.py activity titles/descriptions
        "grammar_title": "Grammar: {label}",
        "grammar_desc": "Review the grammar rule: {label}",
        "reading_title_n": "Reading {n}",
        "reading_title": "Reading",
        "reading_desc": "Read a text about: {topic}",
        "listening_title_n": "Listening {n}",
        "listening_title": "Listening",
        "listening_desc": "Listen and understand: {topic}",
        "listening_reveal_transcript": "Show transcript",
        "listening_hide_transcript": "Hide transcript",
        "drill_title": "Drill: {label}",
        "speaking_title": "Speaking: {label}",
        "speaking_desc": "Practice: {label}",
        "writing_title": "Writing",
        "writing_desc": "Write a text about: {topic}",
        # planner.py vocab activity
        "vocab_title": "Vocabulary ({count} words)",
        "vocab_desc": "Review the words due today",
        # a0.py discovered vocab review
        "vocab_discovered_title": "Quick review ({count} words)",
        "vocab_discovered_desc": "Review words from this lesson",
        # a0.py fallback titles
        "a0_drill_title": "Drill: {code}",
        "a0_reading_title": "Reading",
        "a0_writing_title": "Writing",
    },
    "it": {
        # materialize.py activity titles/descriptions
        "grammar_title": "Grammatica: {label}",
        "grammar_desc": "Ripassa la regola grammaticale: {label}",
        "reading_title_n": "Lettura {n}",
        "reading_title": "Lettura",
        "reading_desc": "Leggi un testo su: {topic}",
        "listening_title_n": "Ascolto {n}",
        "listening_title": "Ascolto",
        "listening_desc": "Ascolta e comprendi: {topic}",
        "listening_reveal_transcript": "Mostra trascrizione",
        "listening_hide_transcript": "Nascondi trascrizione",
        "drill_title": "Esercizio: {label}",
        "speaking_title": "Parlare: {label}",
        "speaking_desc": "Pratica: {label}",
        "writing_title": "Scrittura",
        "writing_desc": "Scrivi un testo su: {topic}",
        # planner.py vocab activity
        "vocab_title": "Vocabolario ({count} parole)",
        "vocab_desc": "Ripassa le parole in scadenza oggi",
        # a0.py discovered vocab review
        "vocab_discovered_title": "Ripasso veloce ({count} parole)",
        "vocab_discovered_desc": "Ripassa le parole di questa lezione",
        # a0.py fallback titles
        "a0_drill_title": "Esercizio: {code}",
        "a0_reading_title": "Lettura",
        "a0_writing_title": "Scrittura",
    },
}


def strings_t(key: str, **kwargs) -> str:
    """Look up a Python-side UI string by key and format with kwargs."""
    lang = settings.UI_LANGUAGE
    table = _STRINGS.get(lang, _STRINGS["en"])
    template = table.get(key, key)
    return template.format(**kwargs) if kwargs else template
