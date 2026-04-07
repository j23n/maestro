"""Unit tests for the TTS (text-to-speech) service.

Azure is never called in these tests — _synth_to_file is patched directly
and _AUDIO_DIR is redirected to tmp_path.
"""

import pytest
from unittest.mock import AsyncMock, patch

import httpx

import maestro.tts as tts_module
from maestro.tts import (
    _slugify,
    phrase_audio_path,
    word_audio_path,
    _lesson_audio_path,
    _synth_to_file,
    generate_word_audio,
    generate_lesson_audio,
)


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_slugify_basic():
    assert _slugify("ciao") == "ciao"


@pytest.mark.unit
def test_slugify_uppercase():
    assert _slugify("Roma") == "roma"


@pytest.mark.unit
def test_slugify_strips_accents():
    assert _slugify("caffè") == "caffe"
    assert _slugify("città") == "citta"
    assert _slugify("perché") == "perche"
    assert _slugify("fiancé") == "fiance"


@pytest.mark.unit
def test_slugify_replaces_spaces():
    assert _slugify("buon giorno") == "buon_giorno"


@pytest.mark.unit
def test_slugify_strips_punctuation():
    assert _slugify("ciao!") == "ciao"
    assert _slugify("(andiamo)") == "andiamo"


@pytest.mark.unit
def test_slugify_collapses_multiple_separators():
    assert _slugify("a  b--c") == "a_b_c"


@pytest.mark.unit
def test_slugify_strips_leading_trailing_underscores():
    assert _slugify("!ciao!") == "ciao"


# ---------------------------------------------------------------------------
# path helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_word_audio_path_plain():
    path = word_audio_path("ciao", language="it")
    assert path.name == "word_ciao.wav"
    assert path.parent.name == "it"


@pytest.mark.unit
def test_word_audio_path_accent():
    path = word_audio_path("caffè", language="it")
    assert path.name == "word_caffe.wav"


@pytest.mark.unit
def test_word_audio_path_language_isolation():
    de_path = word_audio_path("Hotel", language="de")
    it_path = word_audio_path("Hotel", language="it")
    assert de_path != it_path
    assert de_path.parent.name == "de"
    assert it_path.parent.name == "it"


@pytest.mark.unit
def test_word_audio_path_no_language():
    path = word_audio_path("ciao")
    assert path.parent == tts_module._audio_dir()


@pytest.mark.unit
def test_word_audio_path_is_under_audio_dir():
    path = word_audio_path("ciao", language="it")
    assert path.parent.parent == tts_module._audio_dir()


@pytest.mark.unit
def test_phrase_audio_path_basic():
    path = phrase_audio_path("Guten Morgen", language="de")
    assert path.name == "phrase_guten_morgen.wav"
    assert path.parent.name == "de"


@pytest.mark.unit
def test_phrase_audio_path_language_isolation():
    de_path = phrase_audio_path("Danke", language="de")
    it_path = phrase_audio_path("Danke", language="it")
    assert de_path != it_path
    assert de_path.parent.name == "de"
    assert it_path.parent.name == "it"


@pytest.mark.unit
def test_lesson_audio_path_basic():
    path = _lesson_audio_path("abc123", 0)
    assert path.name == "lesson_abc123_0.wav"


@pytest.mark.unit
def test_lesson_audio_path_index():
    path = _lesson_audio_path("xyz", 3)
    assert path.name == "lesson_xyz_3.wav"


@pytest.mark.unit
def test_lesson_audio_path_is_under_audio_dir():
    path = _lesson_audio_path("abc", 0)
    assert path.parent == tts_module._audio_dir()


# ---------------------------------------------------------------------------
# generate_word_audio
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_generate_word_audio_idempotent(tmp_path, monkeypatch):
    """Returns the cached URL immediately when the WAV already exists."""
    monkeypatch.setattr(tts_module, "_audio_dir", lambda: tmp_path)
    (tmp_path / "it").mkdir()
    (tmp_path / "it" / "word_ciao.wav").write_bytes(b"fake wav")

    calls = []

    async def fake_synth(text, path, **kwargs):
        calls.append((text, path))

    monkeypatch.setattr(tts_module, "_synth_to_file", fake_synth)

    url = await generate_word_audio("ciao", language="it")

    assert url == "/static/audio/it/word_ciao.wav"
    assert calls == [], "synthesis should not be called when file already exists"


@pytest.mark.unit
async def test_generate_word_audio_calls_synthesis(tmp_path, monkeypatch):
    """Calls _synth_to_file and returns the URL when file is absent."""
    monkeypatch.setattr(tts_module, "_audio_dir", lambda: tmp_path)

    synth_calls = []

    async def fake_synth(text, path, **kwargs):
        synth_calls.append((text, path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake wav")

    monkeypatch.setattr(tts_module, "_synth_to_file", fake_synth)

    url = await generate_word_audio("ciao", language="it")

    assert url == "/static/audio/it/word_ciao.wav"
    assert len(synth_calls) == 1
    text, path = synth_calls[0]
    assert text == "ciao"
    assert path.name == "word_ciao.wav"


@pytest.mark.unit
async def test_generate_word_audio_returns_none_on_error(tmp_path, monkeypatch):
    """Returns None without raising when synthesis throws."""
    monkeypatch.setattr(tts_module, "_audio_dir", lambda: tmp_path)

    async def fake_synth(text, path, **kwargs):
        raise RuntimeError("synthesis failed")

    monkeypatch.setattr(tts_module, "_synth_to_file", fake_synth)

    url = await generate_word_audio("ciao", language="it")

    assert url is None


@pytest.mark.unit
async def test_generate_word_audio_url_format(tmp_path, monkeypatch):
    """URL must start with /static/audio/ and end with .wav."""
    monkeypatch.setattr(tts_module, "_audio_dir", lambda: tmp_path)

    async def fake_synth(text, path, **kwargs):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"wav")

    monkeypatch.setattr(tts_module, "_synth_to_file", fake_synth)

    url = await generate_word_audio("parlare", language="it")

    assert url is not None
    assert url.startswith("/static/audio/")
    assert url.endswith(".wav")


# ---------------------------------------------------------------------------
# generate_lesson_audio
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_generate_lesson_audio_idempotent(tmp_path, monkeypatch):
    """Returns the cached URL immediately when the WAV already exists."""
    monkeypatch.setattr(tts_module, "_audio_dir", lambda: tmp_path)
    (tmp_path / "lesson_abc123_0.wav").write_bytes(b"fake wav")

    calls = []

    async def fake_synth(text, path, **kwargs):
        calls.append((text, path))

    monkeypatch.setattr(tts_module, "_synth_to_file", fake_synth)

    url = await generate_lesson_audio("Marco va al bar.", "abc123", 0, language="it")

    assert url == "/static/audio/lesson_abc123_0.wav"
    assert calls == [], "synthesis should not be called when file already exists"


@pytest.mark.unit
async def test_generate_lesson_audio_calls_synthesis(tmp_path, monkeypatch):
    """Calls _synth_to_file and returns the URL when file is absent."""
    monkeypatch.setattr(tts_module, "_audio_dir", lambda: tmp_path)

    synth_calls = []

    async def fake_synth(text, path, **kwargs):
        synth_calls.append((text, path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake wav")

    monkeypatch.setattr(tts_module, "_synth_to_file", fake_synth)

    url = await generate_lesson_audio("Marco va al bar.", "abc123", 2, language="it")

    assert url == "/static/audio/lesson_abc123_2.wav"
    assert len(synth_calls) == 1
    text, path = synth_calls[0]
    assert text == "Marco va al bar."
    assert path.name == "lesson_abc123_2.wav"


@pytest.mark.unit
async def test_generate_lesson_audio_returns_none_on_error(tmp_path, monkeypatch):
    """Returns None without raising when synthesis throws."""
    monkeypatch.setattr(tts_module, "_audio_dir", lambda: tmp_path)

    async def fake_synth(text, path, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(tts_module, "_synth_to_file", fake_synth)

    url = await generate_lesson_audio("Testo.", "abc123", 0, language="it")

    assert url is None


@pytest.mark.unit
async def test_generate_lesson_audio_url_format(tmp_path, monkeypatch):
    """URL must start with /static/audio/ and end with .wav."""
    monkeypatch.setattr(tts_module, "_audio_dir", lambda: tmp_path)

    async def fake_synth(text, path, **kwargs):
        path.write_bytes(b"wav")

    monkeypatch.setattr(tts_module, "_synth_to_file", fake_synth)

    url = await generate_lesson_audio("Testo.", "lesson999", 1, language="it")

    assert url is not None
    assert url.startswith("/static/audio/")
    assert url.endswith(".wav")


@pytest.mark.unit
async def test_generate_lesson_audio_different_indices_different_files(
    tmp_path, monkeypatch
):
    """Each (lesson_id, idx) pair produces a distinct WAV file."""
    monkeypatch.setattr(tts_module, "_audio_dir", lambda: tmp_path)

    created = []

    async def fake_synth(text, path, **kwargs):
        path.write_bytes(b"wav")
        created.append(path.name)

    monkeypatch.setattr(tts_module, "_synth_to_file", fake_synth)

    url0 = await generate_lesson_audio("Prima lettura.", "lesson1", 0, language="it")
    url1 = await generate_lesson_audio("Seconda lettura.", "lesson1", 1, language="it")

    assert url0 != url1
    assert "lesson_lesson1_0.wav" in created
    assert "lesson_lesson1_1.wav" in created


# ---------------------------------------------------------------------------
# _synth_to_file — Azure error translation to provider-agnostic exceptions
# ---------------------------------------------------------------------------


def _mock_tts_client_with_error(side_effect):
    """Return a mock httpx.AsyncClient whose .post raises side_effect."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(side_effect=side_effect)
    return mock_client


@pytest.mark.unit
async def test_synth_to_file_raises_api_timeout_on_httpx_timeout(tmp_path):
    """httpx.TimeoutException is translated to our APITimeoutError."""
    from maestro.errors import APITimeoutError

    mock_client = _mock_tts_client_with_error(httpx.TimeoutException("read timed out"))

    with patch.object(tts_module, "_get_tts_client", return_value=mock_client):
        with pytest.raises(APITimeoutError) as exc_info:
            await _synth_to_file("ciao", tmp_path / "test.wav", language="it")

    assert exc_info.value.provider == "azure"
    assert isinstance(exc_info.value.__cause__, httpx.TimeoutException)


@pytest.mark.unit
async def test_synth_to_file_raises_api_rate_limit_on_429(tmp_path):
    """httpx.HTTPStatusError with 429 is translated to APIRateLimitError."""
    from maestro.errors import APIRateLimitError

    request = httpx.Request("POST", "https://eastus.tts.speech.microsoft.com")
    response = httpx.Response(429, request=request)
    error = httpx.HTTPStatusError(
        "429 Too Many Requests", request=request, response=response
    )

    mock_client = _mock_tts_client_with_error(error)

    with patch.object(tts_module, "_get_tts_client", return_value=mock_client):
        with pytest.raises(APIRateLimitError) as exc_info:
            await _synth_to_file("ciao", tmp_path / "test.wav", language="it")

    assert exc_info.value.provider == "azure"


@pytest.mark.unit
async def test_synth_to_file_raises_api_status_error_on_500(tmp_path):
    """httpx.HTTPStatusError with 500 is translated to our APIStatusError."""
    from maestro.errors import APIStatusError

    request = httpx.Request("POST", "https://eastus.tts.speech.microsoft.com")
    response = httpx.Response(500, request=request)
    error = httpx.HTTPStatusError(
        "500 Internal Server Error", request=request, response=response
    )

    mock_client = _mock_tts_client_with_error(error)

    with patch.object(tts_module, "_get_tts_client", return_value=mock_client):
        with pytest.raises(APIStatusError) as exc_info:
            await _synth_to_file("ciao", tmp_path / "test.wav", language="it")

    assert exc_info.value.status_code == 500
    assert exc_info.value.provider == "azure"


@pytest.mark.unit
async def test_generate_word_audio_returns_none_on_api_unavailable(
    tmp_path, monkeypatch
):
    """generate_word_audio catches APIUnavailableError and returns None."""
    from maestro.errors import APITimeoutError

    monkeypatch.setattr(tts_module, "_audio_dir", lambda: tmp_path)

    async def fake_synth(text, path, **kwargs):
        raise APITimeoutError("timed out", provider="azure")

    monkeypatch.setattr(tts_module, "_synth_to_file", fake_synth)

    url = await generate_word_audio("ciao", language="it")
    assert url is None


@pytest.mark.unit
async def test_generate_lesson_audio_returns_none_on_api_unavailable(
    tmp_path, monkeypatch
):
    """generate_lesson_audio catches APIUnavailableError and returns None."""
    from maestro.errors import APIRateLimitError

    monkeypatch.setattr(tts_module, "_audio_dir", lambda: tmp_path)

    async def fake_synth(text, path, **kwargs):
        raise APIRateLimitError("rate limited", provider="azure")

    monkeypatch.setattr(tts_module, "_synth_to_file", fake_synth)

    url = await generate_lesson_audio("Testo.", "abc123", 0, language="it")
    assert url is None
