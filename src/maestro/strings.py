"""String table for Python-side UI strings (activity titles, descriptions).

Usage:
    from maestro.strings import t
    title = t("grammar_title", label="Present tense")
"""

from maestro.config import settings

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


def t(key: str, **kwargs) -> str:
    """Look up a UI string by key and format with kwargs."""
    lang = settings.UI_LANGUAGE
    table = _STRINGS.get(lang, _STRINGS["en"])
    template = table.get(key, key)
    return template.format(**kwargs) if kwargs else template
