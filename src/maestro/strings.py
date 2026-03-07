"""String table for Python-side UI strings (activity titles, descriptions).

Usage:
    from maestro.strings import t
    title = t("grammar_title", label="Present tense")
"""
from maestro.config import settings

_STRINGS: dict[str, dict[str, str]] = {
    "it": {
        # materialize.py activity titles/descriptions
        "grammar_title": "Grammatica: {label}",
        "grammar_desc": "Ripassa la regola grammaticale: {label}",
        "reading_title_n": "Lettura {n}",
        "reading_title": "Lettura",
        "reading_desc": "Leggi un testo su: {topic}",
        "drill_title": "Esercizio: {label}",
        "speaking_title": "Parlare: {label}",
        "speaking_desc": "Pratica: {label}",
        "writing_title": "Scrittura",
        "writing_desc": "Scrivi un testo su: {topic}",
        # planner.py vocab activity
        "vocab_title": "Vocabolario ({count} parole)",
        "vocab_desc": "Ripassa le parole in scadenza oggi",
        # a0.py fallback titles
        "a0_drill_title": "Esercizio: {code}",
        "a0_reading_title": "Lettura",
        "a0_writing_title": "Scrittura",
    },
}


def t(key: str, **kwargs) -> str:
    """Look up a UI string by key and format with kwargs."""
    lang = settings.TARGET_LANGUAGE
    table = _STRINGS.get(lang, _STRINGS["it"])
    template = table.get(key, key)
    return template.format(**kwargs) if kwargs else template
