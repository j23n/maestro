"""Integration tests for Azure TTS audio generation.

Two categories:
- Mock-transport tests: run always, verify HTTP plumbing without a real key.
- Live-API tests: opt-in via AZURE_SPEECH_KEY env var, synthesise real audio.

Run live tests with:
  AZURE_SPEECH_KEY=... uv run pytest -m tts -v
"""

import os
import struct
from unittest.mock import AsyncMock, MagicMock

import pytest

import maestro.tts as tts_mod
from maestro.tts import generate_word_audio, generate_lesson_audio

pytestmark = [pytest.mark.tts]

_requires_key = pytest.mark.skipif(
    not os.environ.get("AZURE_SPEECH_KEY"),
    reason="AZURE_SPEECH_KEY not set — opt-in with a real Azure Speech key",
)


@pytest.fixture()
def audio_dir(tmp_path, monkeypatch):
    """Redirect audio output to a per-test temp directory."""
    monkeypatch.setattr(tts_mod, "_AUDIO_DIR", tmp_path)
    return tmp_path


def _read_wav_sample_rate(path) -> int:
    """Parse the sample rate from a RIFF WAV header."""
    with open(path, "rb") as f:
        f.read(24)
        (sample_rate,) = struct.unpack("<I", f.read(4))
    return sample_rate


# ---------------------------------------------------------------------------
# Mock-transport: verifies HTTP plumbing without a real Azure key
# ---------------------------------------------------------------------------

# Minimal valid RIFF/WAV header so the file-exists check is realistic.
_FAKE_WAV = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\xc0]\x00\x00\x80\xbb\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"


# No key required — uses mocked httpx transport.
async def test_synth_pipeline_posts_ssml_and_writes_response(audio_dir, monkeypatch):
    """Full pipeline: generate_word_audio → _synth_to_file → Azure POST.

    Uses a mock httpx client — no AZURE_SPEECH_KEY required.
    Verifies:
    - POST is sent to /cognitiveservices/v1
    - Body is well-formed SSML containing the word
    - Content-Type header is set correctly
    - API response bytes are written verbatim to the WAV file
    """
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = _FAKE_WAV

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    monkeypatch.setattr(tts_mod, "_get_tts_client", lambda: mock_client)

    url = await generate_word_audio("ciao")

    assert url == "/static/audio/word_ciao.wav"
    assert (audio_dir / "word_ciao.wav").read_bytes() == _FAKE_WAV

    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == "/cognitiveservices/v1"
    assert kwargs["headers"]["Content-Type"] == "application/ssml+xml"
    body: bytes = kwargs["content"]
    assert b"<speak" in body
    assert b"ciao" in body


# ---------------------------------------------------------------------------
# Live-API tests — skipped unless AZURE_SPEECH_KEY is set
# ---------------------------------------------------------------------------


@_requires_key
async def test_generate_word_audio_returns_url(audio_dir):
    url = await generate_word_audio("ciao")
    assert url == "/static/audio/word_ciao.wav"


@_requires_key
async def test_generate_word_audio_creates_nonempty_file(audio_dir):
    await generate_word_audio("ciao")
    wav_path = audio_dir / "word_ciao.wav"
    assert wav_path.exists()
    assert wav_path.stat().st_size > 0


@_requires_key
async def test_generate_word_audio_valid_wav_properties(audio_dir):
    """WAV must be 24 kHz riff-24khz-16bit-mono-pcm."""
    await generate_word_audio("ciao")
    sr = _read_wav_sample_rate(audio_dir / "word_ciao.wav")
    assert sr == 24000


@_requires_key
async def test_generate_word_audio_idempotent(audio_dir):
    """Second call returns the same URL and does not overwrite the file."""
    url1 = await generate_word_audio("ciao")
    mtime1 = (audio_dir / "word_ciao.wav").stat().st_mtime

    url2 = await generate_word_audio("ciao")
    mtime2 = (audio_dir / "word_ciao.wav").stat().st_mtime

    assert url1 == url2
    assert mtime1 == mtime2, "WAV was overwritten on the second call"


@_requires_key
async def test_generate_word_audio_accent_word(audio_dir):
    """Accented words are slugified correctly and produce valid audio."""
    url = await generate_word_audio("caffè")
    assert url == "/static/audio/word_caffe.wav"
    sr = _read_wav_sample_rate(audio_dir / "word_caffe.wav")
    assert sr == 24000


@_requires_key
async def test_generate_lesson_audio_returns_url(audio_dir):
    url = await generate_lesson_audio("Ciao, mi chiamo Marco.", "lesson_test", 0)
    assert url == "/static/audio/lesson_lesson_test_0.wav"


@_requires_key
async def test_generate_lesson_audio_creates_nonempty_file(audio_dir):
    await generate_lesson_audio("Ciao, mi chiamo Marco.", "lesson_test", 0)
    wav_path = audio_dir / "lesson_lesson_test_0.wav"
    assert wav_path.exists()
    assert wav_path.stat().st_size > 0


@_requires_key
async def test_generate_lesson_audio_valid_wav_properties(audio_dir):
    await generate_lesson_audio("Ciao, mi chiamo Marco.", "lesson_test", 0)
    sr = _read_wav_sample_rate(audio_dir / "lesson_lesson_test_0.wav")
    assert sr == 24000


@_requires_key
async def test_generate_lesson_audio_idempotent(audio_dir):
    """Second call returns the same URL and does not overwrite the file."""
    url1 = await generate_lesson_audio("Testo.", "lesson_idem", 0)
    mtime1 = (audio_dir / "lesson_lesson_idem_0.wav").stat().st_mtime

    url2 = await generate_lesson_audio("Testo.", "lesson_idem", 0)
    mtime2 = (audio_dir / "lesson_lesson_idem_0.wav").stat().st_mtime

    assert url1 == url2
    assert mtime1 == mtime2, "WAV was overwritten on the second call"


@_requires_key
async def test_generate_lesson_audio_different_indices_are_independent(audio_dir):
    """Two readings from the same lesson use distinct file names."""
    url0 = await generate_lesson_audio("Prima lettura.", "lesson_x", 0)
    url1 = await generate_lesson_audio("Seconda lettura.", "lesson_x", 1)

    assert url0 != url1
    assert (audio_dir / "lesson_lesson_x_0.wav").exists()
    assert (audio_dir / "lesson_lesson_x_1.wav").exists()
