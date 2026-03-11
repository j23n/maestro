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

    return Path(settings.STATIC_DIR) / "audio"


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


def _build_ssml(text: str) -> str:
    from maestro.config import settings

    voice = settings.AZURE_TTS_VOICE
    lang = "-".join(voice.split("-")[:2])  # "it-IT" from "it-IT-IsabellaNeural"
    return (
        f'<speak version="1.0" xml:lang="{lang}">'
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


def _word_audio_path(word: str) -> Path:
    return _audio_dir() / f"word_{_slugify(word)}.wav"


def _lesson_audio_path(lesson_id: str, idx: int) -> Path:
    return _audio_dir() / f"lesson_{lesson_id}_{idx}.wav"


async def _synth_to_file(text: str, path: Path) -> None:
    """Call Azure TTS REST API and write the WAV response to path."""
    client = _get_tts_client()
    t0 = time.monotonic()
    try:
        response = await client.post(
            "/cognitiveservices/v1",
            content=_build_ssml(text).encode(),
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


async def generate_word_audio(word: str) -> Optional[str]:
    """Generate WAV for a single word and return its static URL.

    Returns None if synthesis fails.
    """
    path = _word_audio_path(word)
    url = f"/static/audio/{path.name}"
    if path.exists():
        return url
    lock = _synth_locks.setdefault(path, asyncio.Lock())
    async with lock:
        if path.exists():  # re-check after acquiring
            return url
        try:
            await _synth_to_file(word, path)
            return url
        except Exception:
            logger.warning(
                "word TTS synthesis failed", extra={"word": word}, exc_info=True
            )
            return None


def _a0_audio_path(slug: str) -> Path:
    return _audio_dir() / f"a0_{_slugify(slug)}.wav"


async def generate_a0_audio(slug: str, text: str) -> Optional[str]:
    """Generate WAV for A0 static content, keyed by scenario slug.

    Called only by scripts/generate_a0_audio.py. At runtime, audio_path
    is read directly from the pre-authored YAML; this function is not invoked.
    """
    path = _a0_audio_path(slug)
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


async def generate_lesson_audio(text: str, lesson_id: str, idx: int) -> Optional[str]:
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
            await _synth_to_file(_strip_markup(text), path)
            return url
        except Exception:
            logger.warning(
                "lesson TTS synthesis failed",
                extra={"lesson_id": lesson_id, "idx": idx},
                exc_info=True,
            )
            return None
