"""Text-to-speech service using Azure Cognitive Services Speech REST API.

Functions are idempotent — they return the cached URL if the WAV already exists.
The httpx client is cached via lru_cache and reused across calls.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

import httpx

logger = logging.getLogger(__name__)

_AUDIO_DIR = Path(__file__).parent / "static" / "audio"
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


def _slugify(text: str) -> str:
    """Lowercase, strip accents, replace non-alphanum with underscore."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")


def _word_audio_path(word: str) -> Path:
    return _AUDIO_DIR / f"word_{_slugify(word)}.wav"


def _lesson_audio_path(lesson_id: str, idx: int) -> Path:
    return _AUDIO_DIR / f"lesson_{lesson_id}_{idx}.wav"


async def _synth_to_file(text: str, path: Path) -> None:
    """Call Azure TTS REST API and write the WAV response to path."""
    client = _get_tts_client()
    t0 = time.monotonic()
    response = await client.post(
        "/cognitiveservices/v1",
        content=_build_ssml(text).encode(),
        headers={"Content-Type": "application/ssml+xml"},
    )
    response.raise_for_status()
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
            await _synth_to_file(text, path)
            return url
        except Exception:
            logger.warning(
                "lesson TTS synthesis failed",
                extra={"lesson_id": lesson_id, "idx": idx},
                exc_info=True,
            )
            return None
