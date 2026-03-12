"""Pronunciation assessment service using Azure Speech-to-Text REST API.

Mirrors the tts.py pattern: lru_cache httpx client, provider-agnostic errors,
structured logging. Reuses the same AZURE_SPEECH_KEY and AZURE_SPEECH_REGION
settings.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from functools import lru_cache

import httpx
from pydantic import BaseModel

from maestro.errors import (
    APIRateLimitError,
    APIStatusError,
    APITimeoutError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class WordAssessment(BaseModel):
    word: str
    accuracy_score: float
    error_type: str  # "None", "Omission", "Insertion", "Mispronunciation"


class PronunciationResult(BaseModel):
    accuracy_score: float  # 0-100
    fluency_score: float  # 0-100
    completeness_score: float  # 0-100
    pronunciation_score: float  # 0-100 overall
    words: list[WordAssessment]
    recognized_text: str


class TranscriptionResult(BaseModel):
    recognized_text: str
    confidence: float


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _get_stt_client() -> httpx.AsyncClient:
    from maestro.config import settings

    region = settings.AZURE_SPEECH_REGION
    return httpx.AsyncClient(
        base_url=f"https://{region}.stt.speech.microsoft.com",
        headers={
            "Ocp-Apim-Subscription-Key": settings.AZURE_SPEECH_KEY,
            "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
            "Accept": "application/json",
        },
        timeout=60.0,
    )


# ---------------------------------------------------------------------------
# Assessment config builder
# ---------------------------------------------------------------------------


def _build_assessment_header(reference_text: str) -> str:
    """Build the base64-encoded Pronunciation-Assessment header value."""
    config = {
        "ReferenceText": reference_text,
        "GradingSystem": "HundredMark",
        "Granularity": "Word",
        "Dimension": "Comprehensive",
    }
    return base64.b64encode(json.dumps(config).encode()).decode()


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------


def _parse_transcription_response(data: dict) -> TranscriptionResult:
    """Extract a TranscriptionResult from the Azure JSON response."""
    status = data.get("RecognitionStatus", "")
    if status != "Success":
        raise APIStatusError(
            f"Recognition failed: {status}",
            status_code=0,
            provider="azure",
        )

    nbest = data.get("NBest", [])
    if not nbest:
        raise APIStatusError(
            "No recognition results returned",
            status_code=0,
            provider="azure",
        )

    best = nbest[0]
    return TranscriptionResult(
        recognized_text=best.get("Display", ""),
        confidence=best.get("Confidence", 0.0),
    )


def _parse_response(data: dict) -> PronunciationResult:
    """Extract a PronunciationResult from the Azure JSON response."""
    status = data.get("RecognitionStatus", "")
    if status != "Success":
        raise APIStatusError(
            f"Recognition failed: {status}",
            status_code=0,
            provider="azure",
        )

    nbest = data.get("NBest", [])
    if not nbest:
        raise APIStatusError(
            "No recognition results returned",
            status_code=0,
            provider="azure",
        )

    best = nbest[0]
    words = [
        WordAssessment(
            word=w["Word"],
            accuracy_score=w.get("AccuracyScore", 0.0),
            error_type=w.get("ErrorType", "None"),
        )
        for w in best.get("Words", [])
    ]

    return PronunciationResult(
        accuracy_score=best.get("AccuracyScore", 0.0),
        fluency_score=best.get("FluencyScore", 0.0),
        completeness_score=best.get("CompletenessScore", 0.0),
        pronunciation_score=best.get("PronScore", 0.0),
        words=words,
        recognized_text=best.get("Display", ""),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def assess_pronunciation(
    audio_bytes: bytes,
    reference_text: str,
) -> PronunciationResult:
    """Send audio to Azure for pronunciation assessment.

    Args:
        audio_bytes: Raw WAV file bytes (16 kHz, 16-bit, mono PCM).
        reference_text: The text the student was asked to read aloud.

    Returns:
        PronunciationResult with overall and per-word scores.

    Raises:
        APITimeoutError, APIRateLimitError, APIStatusError on failure.
    """
    from maestro.config import settings

    client = _get_stt_client()
    lang_tag = (
        f"{settings.TARGET_LANGUAGE}-{settings.TARGET_LANGUAGE.upper()}"  # "it-IT"
    )

    t0 = time.monotonic()
    try:
        response = await client.post(
            "/speech/recognition/conversation/cognitiveservices/v1",
            params={"language": lang_tag, "format": "detailed"},
            content=audio_bytes,
            headers={
                "Pronunciation-Assessment": _build_assessment_header(reference_text),
            },
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

    result = _parse_response(response.json())
    duration_ms = round((time.monotonic() - t0) * 1000, 1)
    logger.info(
        "stt_assessed",
        extra={
            "ref_chars": len(reference_text),
            "audio_bytes": len(audio_bytes),
            "duration_ms": duration_ms,
            "pronunciation_score": result.pronunciation_score,
        },
    )
    return result


async def transcribe(audio_bytes: bytes) -> TranscriptionResult:
    """Transcribe audio without pronunciation assessment.

    Args:
        audio_bytes: Raw WAV file bytes (16 kHz, 16-bit, mono PCM).

    Returns:
        TranscriptionResult with recognized text and confidence.

    Raises:
        APITimeoutError, APIRateLimitError, APIStatusError on failure.
    """
    from maestro.config import settings

    client = _get_stt_client()
    lang_tag = (
        f"{settings.TARGET_LANGUAGE}-{settings.TARGET_LANGUAGE.upper()}"  # "it-IT"
    )

    t0 = time.monotonic()
    try:
        response = await client.post(
            "/speech/recognition/conversation/cognitiveservices/v1",
            params={"language": lang_tag, "format": "detailed"},
            content=audio_bytes,
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

    result = _parse_transcription_response(response.json())
    duration_ms = round((time.monotonic() - t0) * 1000, 1)
    logger.info(
        "stt_transcribed",
        extra={
            "audio_bytes": len(audio_bytes),
            "duration_ms": duration_ms,
            "confidence": result.confidence,
            "text_len": len(result.recognized_text),
        },
    )
    return result
