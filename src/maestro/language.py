"""Language configuration registry.

Maps ISO 639-1 language codes to per-language config (NLP model, TTS voice, etc.).
Used to resolve per-student target language into concrete service parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LanguageConfig:
    """All language-specific parameters needed to serve a student."""

    code: str  # ISO 639-1, e.g. "it"
    name: str  # human-readable, e.g. "Italian"
    flag: str  # emoji flag, e.g. "🇮🇹"
    spacy_model: str  # e.g. "it_core_news_md"
    tts_voice: str  # Azure TTS voice name for single-speaker synthesis
    stt_locale: str  # e.g. "it-IT"
    # Voices cycled through for multi-speaker dialogue synthesis.  First voice
    # is typically male, second female (so the default `tts_voice` matches
    # voices[1] — single-phrase audio stays consistent with one speaker of
    # the dialogue pair).
    tts_conversation_voices: tuple[str, ...] = field(default_factory=tuple)


LANGUAGES: dict[str, LanguageConfig] = {
    "it": LanguageConfig(
        code="it",
        name="Italian",
        flag="🇮🇹",
        spacy_model="it_core_news_md",
        tts_voice="it-IT-IsabellaNeural",
        stt_locale="it-IT",
        tts_conversation_voices=("it-IT-DiegoNeural", "it-IT-IsabellaNeural"),
    ),
    "de": LanguageConfig(
        code="de",
        name="German",
        flag="🇩🇪",
        spacy_model="de_core_news_md",
        tts_voice="de-DE-KatjaNeural",
        stt_locale="de-DE",
        tts_conversation_voices=("de-DE-ConradNeural", "de-DE-KatjaNeural"),
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
