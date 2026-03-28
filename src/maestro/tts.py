"""Text-to-speech service using Azure Cognitive Services Speech REST API.

Functions are idempotent — they return the cached URL if the WAV already exists.
The httpx client is cached via lru_cache and reused across calls.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

import httpx

from maestro.errors import (
    APIRateLimitError,
    APIStatusError,
    APITimeoutError,
)

logger = logging.getLogger(__name__)


def _audio_dir() -> Path:
    from maestro.config import settings

    return Path(settings.DATA_DIR) / "audio"


_synth_locks: dict[Path, asyncio.Lock] = {}


@lru_cache(maxsize=1)
def _get_tts_client() -> httpx.AsyncClient:
    from maestro.config import settings

    region = settings.AZURE_SPEECH_REGION
    return httpx.AsyncClient(
        base_url=f"https://{region}.tts.speech.microsoft.com",
        headers={
            "Ocp-Apim-Subscription-Key": settings.AZURE_SPEECH_KEY,
            "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
            "User-Agent": "maestro-tts/1.0",
        },
        timeout=60.0,
    )


def _build_ssml(text: str, *, language: str | None = None) -> str:
    from maestro.language import DEFAULT_LANGUAGE, get_language_config

    lang_cfg = get_language_config(language or DEFAULT_LANGUAGE)
    voice = lang_cfg.tts_voice
    locale = lang_cfg.stt_locale
    return (
        f'<speak version="1.0" xml:lang="{locale}">'
        f'<voice name="{voice}">{escape(text)}</voice>'
        f"</speak>"
    )


def _strip_markup(text: str) -> str:
    """Remove HTML tags and decode entities for plain-text TTS input."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def _slugify(text: str) -> str:
    """Lowercase, strip accents, replace non-alphanum with underscore."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")


def word_audio_path(word: str) -> Path:
    return _audio_dir() / f"word_{_slugify(word)}.wav"


def _lesson_audio_path(lesson_id: str, idx: int) -> Path:
    return _audio_dir() / f"lesson_{lesson_id}_{idx}.wav"


async def _synth_to_file(text: str, path: Path, *, language: str | None = None) -> None:
    """Call Azure TTS REST API and write the WAV response to path."""
    client = _get_tts_client()
    t0 = time.monotonic()
    try:
        response = await client.post(
            "/cognitiveservices/v1",
            content=_build_ssml(text, language=language).encode(),
            headers={"Content-Type": "application/ssml+xml"},
        )
        response.raise_for_status()
    except httpx.TimeoutException as e:
        raise APITimeoutError("Timeout", provider="azure") from e
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            raise APIRateLimitError("Rate limited", provider="azure") from e
        raise APIStatusError(
            f"API error {e.response.status_code}",
            status_code=e.response.status_code,
            provider="azure",
        ) from e
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    logger.info(
        "tts_synthesized",
        extra={
            "chars": len(text),
            "path": str(path),
            "duration_ms": round((time.monotonic() - t0) * 1000, 1),
            "cost_usd": round(len(text) * 15.0 / 1_000_000, 6),
        },
    )


async def generate_word_audio(
    word: str, *, language: str | None = None
) -> Optional[str]:
    """Generate WAV for a single word and return its static URL.

    Returns None if synthesis fails.
    """
    path = word_audio_path(word)
    url = f"/static/audio/{path.name}"
    if path.exists():
        return url
    lock = _synth_locks.setdefault(path, asyncio.Lock())
    async with lock:
        if path.exists():  # re-check after acquiring
            return url
        try:
            await _synth_to_file(word, path, language=language)
            return url
        except Exception:
            logger.warning(
                "word TTS synthesis failed", extra={"word": word}, exc_info=True
            )
            return None


def a0_audio_path(slug: str) -> Path:
    return _audio_dir() / f"a0_{_slugify(slug)}.wav"


async def generate_a0_audio(slug: str, text: str) -> Optional[str]:
    """Generate WAV for A0 static content, keyed by scenario slug.

    Called only by scripts/generate_a0_audio.py. At runtime, audio_path
    is read directly from the pre-authored YAML; this function is not invoked.
    """
    path = a0_audio_path(slug)
    url = f"/static/audio/{path.name}"
    if path.exists():
        return url
    lock = _synth_locks.setdefault(path, asyncio.Lock())
    async with lock:
        if path.exists():
            return url
        try:
            await _synth_to_file(_strip_markup(text), path)
            return url
        except Exception:
            logger.warning(
                "a0 TTS synthesis failed", extra={"slug": slug}, exc_info=True
            )
            return None


async def sync_a0_listening_audio() -> None:
    """Generate missing WAV files for A0 listening activities.

    Reads a0_lessons.yaml, finds listening activities with audio_path set,
    and synthesizes any that don't exist on disk yet. Skips silently if
    Azure credentials are not configured.
    """
    from maestro.config import settings

    if not settings.AZURE_SPEECH_KEY or not settings.AZURE_SPEECH_REGION:
        logger.info("a0_audio_sync: no Azure credentials, skipping audio generation")
        return

    import yaml
    from maestro.utils import data_dir

    lessons_path = data_dir() / "a0_lessons.yaml"
    if not lessons_path.exists():
        return

    with open(lessons_path) as f:
        all_lessons = yaml.safe_load(f)

    audio_dir = _audio_dir()
    audio_dir.mkdir(parents=True, exist_ok=True)

    generated = 0
    for slug, lesson_data in all_lessons.items():
        for act in lesson_data.get("activities", []):
            if act.get("type") != "listening":
                continue
            audio_url = act.get("audio_path")
            content = act.get("content", "")
            if not audio_url or not content:
                continue
            # audio_path is e.g. "/static/audio/a0_01_in_aereo.wav"
            filename = audio_url.rsplit("/", 1)[-1]
            path = audio_dir / filename
            if path.exists():
                continue
            try:
                await _synth_to_file(_strip_markup(content), path)
                generated += 1
                logger.info("a0_audio_sync: generated %s", filename)
            except Exception:
                logger.warning(
                    "a0_audio_sync: failed to generate %s",
                    filename,
                    exc_info=True,
                )

    if generated:
        logger.info("a0_audio_sync: generated %d listening audio files", generated)
    else:
        logger.info("a0_audio_sync: all listening audio up to date")


async def generate_lesson_audio(
    text: str,
    lesson_id: str,
    idx: int,
    *,
    language: str | None = None,
) -> Optional[str]:
    """Generate WAV for a lesson reading and return its static URL.

    Returns None if synthesis fails.
    """
    path = _lesson_audio_path(lesson_id, idx)
    url = f"/static/audio/{path.name}"
    if path.exists():
        return url
    lock = _synth_locks.setdefault(path, asyncio.Lock())
    async with lock:
        if path.exists():  # re-check after acquiring
            return url
        try:
            await _synth_to_file(_strip_markup(text), path, language=language)
            return url
        except Exception:
            logger.warning(
                "lesson TTS synthesis failed",
                extra={"lesson_id": lesson_id, "idx": idx},
                exc_info=True,
            )
            return None
