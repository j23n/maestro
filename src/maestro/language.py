"""Language configuration registry.

Maps ISO 639-1 language codes to per-language config (NLP model, TTS voice, etc.).
Used to resolve per-student target language into concrete service parameters.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageConfig:
    """All language-specific parameters needed to serve a student."""

    code: str  # ISO 639-1, e.g. "it"
    name: str  # human-readable, e.g. "Italian"
    spacy_model: str  # e.g. "it_core_news_md"
    tts_voice: str  # Azure TTS voice name
    stt_locale: str  # e.g. "it-IT"


LANGUAGES: dict[str, LanguageConfig] = {
    "it": LanguageConfig(
        code="it",
        name="Italian",
        spacy_model="it_core_news_md",
        tts_voice="it-IT-IsabellaNeural",
        stt_locale="it-IT",
    ),
    "de": LanguageConfig(
        code="de",
        name="German",
        spacy_model="de_core_news_sm",
        tts_voice="de-DE-KatjaNeural",
        stt_locale="de-DE",
    ),
}


def all_language_codes() -> list[str]:
    """Return all supported language codes."""
    return list(LANGUAGES.keys())


def get_language_config(code: str) -> LanguageConfig:
    """Look up a LanguageConfig by ISO code. Raises ValueError for unknown codes."""
    try:
        return LANGUAGES[code]
    except KeyError:
        raise ValueError(
            f"Unsupported language '{code}'. Available: {', '.join(sorted(LANGUAGES))}"
        )
