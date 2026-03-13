"""Unit tests for the STT (speech-to-text) pronunciation assessment service.

Azure is never called — the httpx client is mocked.
"""

import base64
import json

import httpx
import pytest
from unittest.mock import AsyncMock, patch

import maestro.stt as stt_module
from maestro.stt import (
    _build_assessment_header,
    _parse_response,
    _parse_transcription_response,
    assess_pronunciation,
    transcribe,
    PronunciationResult,
    TranscriptionResult,
)


# ---------------------------------------------------------------------------
# _build_assessment_header
# ---------------------------------------------------------------------------

SAMPLE_AZURE_RESPONSE = {
    "RecognitionStatus": "Success",
    "Offset": 700000,
    "Duration": 8400000,
    "DisplayText": "Buon giorno.",
    "NBest": [
        {
            "Confidence": 0.95,
            "Lexical": "buon giorno",
            "Display": "Buon giorno.",
            "AccuracyScore": 92.0,
            "FluencyScore": 88.0,
            "CompletenessScore": 100.0,
            "PronScore": 90.5,
            "Words": [
                {
                    "Word": "buon",
                    "Offset": 700000,
                    "Duration": 2600000,
                    "AccuracyScore": 95.0,
                    "ErrorType": "None",
                },
                {
                    "Word": "giorno",
                    "Offset": 3400000,
                    "Duration": 5700000,
                    "AccuracyScore": 89.0,
                    "ErrorType": "None",
                },
            ],
        }
    ],
}


@pytest.mark.unit
def test_build_assessment_header_is_base64():
    header = _build_assessment_header("Buon giorno.")
    decoded = json.loads(base64.b64decode(header))
    assert decoded["ReferenceText"] == "Buon giorno."
    assert decoded["GradingSystem"] == "HundredMark"
    assert decoded["Granularity"] == "Word"
    assert decoded["Dimension"] == "Comprehensive"


@pytest.mark.unit
def test_build_assessment_header_roundtrip():
    """Decoding the header yields the original config."""
    text = "Che bella giornata!"
    header = _build_assessment_header(text)
    decoded = json.loads(base64.b64decode(header))
    assert decoded["ReferenceText"] == text


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_response_success():
    result = _parse_response(SAMPLE_AZURE_RESPONSE)
    assert isinstance(result, PronunciationResult)
    assert result.accuracy_score == 92.0
    assert result.fluency_score == 88.0
    assert result.completeness_score == 100.0
    assert result.pronunciation_score == 90.5
    assert result.recognized_text == "Buon giorno."
    assert len(result.words) == 2
    assert result.words[0].word == "buon"
    assert result.words[0].accuracy_score == 95.0
    assert result.words[0].error_type == "None"
    assert result.words[0].offset_seconds == pytest.approx(0.07)
    assert result.words[0].duration_seconds == pytest.approx(0.26)
    assert result.words[1].word == "giorno"
    assert result.words[1].offset_seconds == pytest.approx(0.34)
    assert result.words[1].duration_seconds == pytest.approx(0.57)


@pytest.mark.unit
def test_parse_response_no_match():
    """Recognition failure raises APIStatusError."""
    from maestro.errors import APIStatusError

    with pytest.raises(APIStatusError, match="Recognition failed"):
        _parse_response({"RecognitionStatus": "NoMatch"})


@pytest.mark.unit
def test_parse_response_empty_nbest():
    """Empty NBest list raises APIStatusError."""
    from maestro.errors import APIStatusError

    with pytest.raises(APIStatusError, match="No recognition results"):
        _parse_response({"RecognitionStatus": "Success", "NBest": []})


@pytest.mark.unit
def test_parse_response_word_with_mispronunciation():
    data = {
        "RecognitionStatus": "Success",
        "NBest": [
            {
                "AccuracyScore": 60.0,
                "FluencyScore": 70.0,
                "CompletenessScore": 50.0,
                "PronScore": 55.0,
                "Display": "Buon giorno.",
                "Words": [
                    {
                        "Word": "buon",
                        "AccuracyScore": 80.0,
                        "ErrorType": "None",
                    },
                    {
                        "Word": "giorno",
                        "AccuracyScore": 40.0,
                        "ErrorType": "Mispronunciation",
                    },
                ],
            }
        ],
    }
    result = _parse_response(data)
    assert result.words[1].error_type == "Mispronunciation"
    assert result.words[1].accuracy_score == 40.0


@pytest.mark.unit
def test_parse_response_omitted_word():
    data = {
        "RecognitionStatus": "Success",
        "NBest": [
            {
                "AccuracyScore": 50.0,
                "FluencyScore": 60.0,
                "CompletenessScore": 50.0,
                "PronScore": 50.0,
                "Display": "Buon.",
                "Words": [
                    {
                        "Word": "buon",
                        "AccuracyScore": 90.0,
                        "ErrorType": "None",
                    },
                    {
                        "Word": "giorno",
                        "AccuracyScore": 0.0,
                        "ErrorType": "Omission",
                    },
                ],
            }
        ],
    }
    result = _parse_response(data)
    assert result.words[1].error_type == "Omission"


# ---------------------------------------------------------------------------
# assess_pronunciation — error translation
# ---------------------------------------------------------------------------


def _mock_stt_client_with_error(side_effect):
    """Return a mock httpx.AsyncClient whose .post raises side_effect."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(side_effect=side_effect)
    return mock_client


def _mock_stt_client_with_response(json_data, status_code=200):
    """Return a mock httpx.AsyncClient whose .post returns a response."""
    from unittest.mock import MagicMock

    # Use MagicMock for the response so .json() is synchronous (like real httpx)
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.unit
async def test_assess_pronunciation_success():
    mock_client = _mock_stt_client_with_response(SAMPLE_AZURE_RESPONSE)

    with patch.object(stt_module, "_get_stt_client", return_value=mock_client):
        result = await assess_pronunciation(b"fake-wav-bytes", "Buon giorno.")

    assert isinstance(result, PronunciationResult)
    assert result.pronunciation_score == 90.5
    assert len(result.words) == 2

    # Verify the POST was called with correct params
    call_kwargs = mock_client.post.call_args
    assert "language" in call_kwargs.kwargs["params"]
    assert call_kwargs.kwargs["params"]["format"] == "detailed"
    assert "Pronunciation-Assessment" in call_kwargs.kwargs["headers"]


@pytest.mark.unit
async def test_assess_pronunciation_timeout():
    from maestro.errors import APITimeoutError

    mock_client = _mock_stt_client_with_error(httpx.TimeoutException("read timed out"))

    with patch.object(stt_module, "_get_stt_client", return_value=mock_client):
        with pytest.raises(APITimeoutError) as exc_info:
            await assess_pronunciation(b"wav", "ciao")

    assert exc_info.value.provider == "azure"


@pytest.mark.unit
async def test_assess_pronunciation_rate_limit():
    from maestro.errors import APIRateLimitError

    request = httpx.Request("POST", "https://eastus.stt.speech.microsoft.com")
    response = httpx.Response(429, request=request)
    error = httpx.HTTPStatusError("429", request=request, response=response)

    mock_client = _mock_stt_client_with_error(error)

    with patch.object(stt_module, "_get_stt_client", return_value=mock_client):
        with pytest.raises(APIRateLimitError) as exc_info:
            await assess_pronunciation(b"wav", "ciao")

    assert exc_info.value.provider == "azure"


@pytest.mark.unit
async def test_assess_pronunciation_server_error():
    from maestro.errors import APIStatusError

    request = httpx.Request("POST", "https://eastus.stt.speech.microsoft.com")
    response = httpx.Response(500, request=request)
    error = httpx.HTTPStatusError("500", request=request, response=response)

    mock_client = _mock_stt_client_with_error(error)

    with patch.object(stt_module, "_get_stt_client", return_value=mock_client):
        with pytest.raises(APIStatusError) as exc_info:
            await assess_pronunciation(b"wav", "ciao")

    assert exc_info.value.status_code == 500
    assert exc_info.value.provider == "azure"


@pytest.mark.unit
async def test_assess_pronunciation_recognition_failure():
    """NoMatch status from Azure raises APIStatusError."""
    from maestro.errors import APIStatusError

    fail_response = {"RecognitionStatus": "NoMatch"}
    mock_client = _mock_stt_client_with_response(fail_response)

    with patch.object(stt_module, "_get_stt_client", return_value=mock_client):
        with pytest.raises(APIStatusError, match="Recognition failed"):
            await assess_pronunciation(b"wav", "ciao")


# ---------------------------------------------------------------------------
# _parse_transcription_response
# ---------------------------------------------------------------------------

SAMPLE_TRANSCRIPTION_RESPONSE = {
    "RecognitionStatus": "Success",
    "Offset": 700000,
    "Duration": 8400000,
    "DisplayText": "La mia famiglia è grande.",
    "NBest": [
        {
            "Confidence": 0.92,
            "Lexical": "la mia famiglia è grande",
            "Display": "La mia famiglia è grande.",
        }
    ],
}


@pytest.mark.unit
def test_parse_transcription_response_success():
    result = _parse_transcription_response(SAMPLE_TRANSCRIPTION_RESPONSE)
    assert isinstance(result, TranscriptionResult)
    assert result.recognized_text == "La mia famiglia è grande."
    assert result.confidence == 0.92


@pytest.mark.unit
def test_parse_transcription_response_no_match():
    """NoMatch status raises APIStatusError."""
    from maestro.errors import APIStatusError

    with pytest.raises(APIStatusError, match="Recognition failed"):
        _parse_transcription_response({"RecognitionStatus": "NoMatch"})


@pytest.mark.unit
def test_parse_transcription_response_empty_nbest():
    from maestro.errors import APIStatusError

    with pytest.raises(APIStatusError, match="No recognition results"):
        _parse_transcription_response({"RecognitionStatus": "Success", "NBest": []})


# ---------------------------------------------------------------------------
# transcribe — end-to-end with mocked client
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_transcribe_success():
    mock_client = _mock_stt_client_with_response(SAMPLE_TRANSCRIPTION_RESPONSE)

    with patch.object(stt_module, "_get_stt_client", return_value=mock_client):
        result = await transcribe(b"fake-wav-bytes")

    assert isinstance(result, TranscriptionResult)
    assert result.recognized_text == "La mia famiglia è grande."
    assert result.confidence == 0.92

    # Verify no Pronunciation-Assessment header was sent
    call_kwargs = mock_client.post.call_args
    assert (
        "headers" not in call_kwargs.kwargs
        or "Pronunciation-Assessment" not in call_kwargs.kwargs.get("headers", {})
    )


@pytest.mark.unit
async def test_transcribe_timeout():
    from maestro.errors import APITimeoutError

    mock_client = _mock_stt_client_with_error(httpx.TimeoutException("read timed out"))

    with patch.object(stt_module, "_get_stt_client", return_value=mock_client):
        with pytest.raises(APITimeoutError) as exc_info:
            await transcribe(b"wav")

    assert exc_info.value.provider == "azure"


@pytest.mark.unit
async def test_transcribe_no_match():
    """NoMatch status from Azure raises APIStatusError."""
    from maestro.errors import APIStatusError

    fail_response = {"RecognitionStatus": "NoMatch"}
    mock_client = _mock_stt_client_with_response(fail_response)

    with patch.object(stt_module, "_get_stt_client", return_value=mock_client):
        with pytest.raises(APIStatusError, match="Recognition failed"):
            await transcribe(b"wav")
