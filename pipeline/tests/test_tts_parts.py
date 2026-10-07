"""M5.1 building blocks: voices, SSML, cache keys, the Azure batch client (recorded responses, no network),
word-boundary alignment, PCM assembly with exact timings, and the single AAC encode."""

from __future__ import annotations

import io
import json
import shutil
import wave
import zipfile

import pytest

from itcontent import audio_pcm as pcm
from itcontent import yamlio
from itcontent.tts_azure import (
    AlignmentError,
    AzureBatchClient,
    AzureError,
    Voice,
    VoiceBook,
    WordBoundary,
    align,
    apply_overrides,
    cache_key,
    cost_usd,
    fnv1a64,
    ssml,
)

# ---------------------------------------------------------------- voices and SSML


def test_voicebook_follows_voices_yaml(root):
    vb = VoiceBook(yamlio.load(root / "content" / "voices.yaml"))
    assert vb.for_speaker("ch:giulia").name == "it-IT-IsabellaNeural"
    assert vb.for_speaker("ch:giulia").rate == "+8%"
    assert vb.for_speaker("ch:narrator").name == "it-IT-ElsaNeural"
    assert vb.for_speaker("ch:announcer").station
    assert vb.for_speaker("ch:you", gender="f").name == "it-IT-FabiolaNeural"
    assert vb.for_speaker("ch:you", gender="m").name == "it-IT-LisandroNeural"
    assert vb.for_items().rate == "-10%"
    extras = ["it-IT-GianniNeural", "it-IT-CataldoNeural", "it-IT-IrmaNeural", "it-IT-BenignoNeural"]
    assert vb.for_speaker("ch:extra", text_id="u02.check.01.audio").name == extras[fnv1a64("u02.check.01.audio") % 4]
    with pytest.raises(KeyError):
        vb.for_speaker("ch:nobody")


def test_fnv1a64_vectors():
    assert fnv1a64("") == 0xCBF29CE484222325
    assert fnv1a64("a") == 0xAF63DC4C8601EC8C


def test_ssml_with_phoneme_override_and_escaping():
    parts = apply_overrides("Ancora un caffè & un cornetto?", {"ancora": "anˈkoːra"})
    assert parts[0] == ("Ancora", "anˈkoːra")
    s = ssml(parts, Voice("it-IT-ElsaNeural", rate="-10%"))
    assert '<voice name="it-IT-ElsaNeural">' in s
    assert '<prosody rate="-10%">' in s
    assert '<phoneme alphabet="ipa" ph="anˈkoːra">Ancora</phoneme>' in s
    assert "&amp;" in s and 'xml:lang="it-IT"' in s


def test_cache_key_changes_with_every_input():
    v = Voice("it-IT-ElsaNeural")
    base = cache_key(v, "<speak/>")
    assert base == cache_key(Voice("it-IT-ElsaNeural"), "<speak/>")
    assert base != cache_key(Voice("it-IT-ElsaNeural", rate="-10%"), "<speak/>")
    assert base != cache_key(Voice("it-IT-ElsaNeural", pitch="+15%"), "<speak/>")
    assert base != cache_key(Voice("it-IT-DiegoNeural"), "<speak/>")
    assert base != cache_key(v, "<speak> </speak>")
    assert base != cache_key(v, "<speak/>", "riff-48khz-16bit-mono-pcm")


def test_cost_estimate():
    assert cost_usd(1_000_000) == 15.0
    assert round(cost_usd(12_345), 4) == 0.1852


# ---------------------------------------------------------------- Azure client with recorded responses


def _wav_bytes(ms: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24_000)
        w.writeframes(b"\x01\x00" * (24 * ms))
    return buf.getvalue()


class Resp:
    def __init__(self, status: int, body: object = None, content: bytes = b"") -> None:
        self.status_code = status
        self._body = body
        self.content = content
        self.text = json.dumps(body) if body is not None else ""

    def json(self) -> object:
        return self._body


class RecordedSession:
    """Replays the Azure batch synthesis exchange (docs/04 § Audio step 4) and records the requests."""

    def __init__(self, polls: list[str], zip_bytes: bytes) -> None:
        self.polls = list(polls)
        self.zip = zip_bytes
        self.requests: list[tuple[str, str, dict | None]] = []

    def put(self, url, headers, data):
        self.requests.append(("PUT", url, json.loads(data)))
        return Resp(201, {"id": "job", "status": "NotStarted"})

    def get(self, url, headers=None):
        self.requests.append(("GET", url, None))
        if url.startswith("https://results.example"):
            return Resp(200, content=self.zip)
        status = self.polls.pop(0)
        body = {"id": "job", "status": status}
        if status == "Succeeded":
            body["outputs"] = {"result": "https://results.example/job.zip"}
        return Resp(200, body)


def _result_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("0001.wav", _wav_bytes(500))
        zf.writestr(
            "0001.word.json",
            json.dumps(
                [
                    {"Text": "Buongiorno", "AudioOffset": 50, "Duration": 400},
                    {"Text": "!", "AudioOffset": 450, "Duration": 0},
                ]
            ),
        )
        zf.writestr("0002.wav", _wav_bytes(300))
        zf.writestr("0002.word.json", "﻿" + json.dumps([{"Text": "Ciao", "AudioOffset": 20, "Duration": 250}]))
        zf.writestr("summary.json", "{}")
    return buf.getvalue()


def test_azure_batch_job_put_poll_download():
    session = RecordedSession(["NotStarted", "Running", "Succeeded"], _result_zip())
    slept = []
    client = AzureBatchClient(
        session, endpoint="https://westeurope.api.cognitive.microsoft.com", key="k", sleep=slept.append, poll_seconds=5
    )
    results = client.synthesize("italiano-test-1", ["<speak>a</speak>", "<speak>b</speak>"])
    method, url, body = session.requests[0]
    assert method == "PUT"
    assert url == (
        "https://westeurope.api.cognitive.microsoft.com/texttospeech/batchsyntheses/italiano-test-1"
        "?api-version=2024-04-01"
    )
    assert body["inputKind"] == "SSML" and len(body["inputs"]) == 2
    assert body["properties"]["outputFormat"] == "riff-24khz-16bit-mono-pcm"
    assert body["properties"]["wordBoundaryEnabled"] is True
    assert body["properties"]["sentenceBoundaryEnabled"] is True
    assert slept == [5, 5]
    assert [r.boundaries[0].text for r in results] == ["Buongiorno", "Ciao"]
    assert results[0].boundaries[1].text == "!"


def test_azure_failures_are_errors():
    session = RecordedSession(["Failed"], b"")
    client = AzureBatchClient(session, endpoint="https://x", key="k", sleep=lambda _: None)
    with pytest.raises(AzureError, match="failed"):
        client.synthesize("j", ["<speak/>"])
    with pytest.raises(AzureError, match="at most 1000"):
        client.synthesize("j", ["<speak/>"] * 1001)


def test_azure_needs_credentials_from_the_environment(monkeypatch):
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_ENDPOINT", raising=False)
    with pytest.raises(AzureError, match="AZURE_SPEECH_KEY"):
        AzureBatchClient(object())


# ---------------------------------------------------------------- alignment


def wb(text: str, start: int, dur: int) -> WordBoundary:
    return WordBoundary(text, start, dur)


def test_align_skips_punctuation_and_matches_in_order():
    bounds = [wb("Scusi", 0, 300), wb(",", 300, 0), wb("quant'è", 400, 500), wb("?", 900, 0)]
    times = align(["Scusi", "quant'", "è"], bounds, "u02.l1.story#19")
    assert times[0] == (0, 300)
    assert times[1][0] == 400 and times[2][1] == 900  # one boundary split over two tokens by character share
    assert times[1][1] == times[2][0]


def test_align_token_spanning_two_boundaries():
    assert align(["e-mail"], [wb("e", 0, 100), wb("-", 100, 0), wb("mail", 120, 200)], "x") == [(0, 320)]


def test_align_mismatch_names_the_line():
    with pytest.raises(AlignmentError, match=r"u02\.l1\.story#20"):
        align(["Sei", "euro"], [wb("6", 0, 100), wb("euro", 100, 100)], "u02.l1.story#20")
    with pytest.raises(AlignmentError, match="audio ends"):
        align(["Sei", "euro"], [wb("Sei", 0, 100)], "x")


# ---------------------------------------------------------------- PCM assembly and encoding


def test_assemble_gaps_and_timings_from_sample_counts():
    a = pcm.Pcm(b"\x00\x00" * 24_000)  # 1 s
    b = pcm.Pcm(b"\x00\x00" * 12_000)  # 0.5 s
    joined, placed = pcm.assemble(
        [
            pcm.Segment(a, "ch:giulia"),
            pcm.Segment(b, "ch:giulia", pause_ms=200),
            pcm.Segment(a, "ch:marco"),
        ]
    )
    assert [(p.start_ms, p.end_ms) for p in placed] == [(0, 1000), (1300, 1800), (2600, 3600)]
    assert joined.duration_ms == 3600


def test_wav_roundtrip_and_format_check(tmp_path):
    p = pcm.Pcm(b"\x01\x02" * 2400)
    pcm.write_wav(p, tmp_path / "a.wav")
    assert pcm.read_wav(tmp_path / "a.wav") == p
    with wave.open(str(tmp_path / "bad.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44_100)
        w.writeframes(b"\x00" * 400)
    with pytest.raises(ValueError, match="riff-24khz-16bit-mono-pcm"):
        pcm.read_wav(tmp_path / "bad.wav")


def test_audio_id_depends_on_pcm_and_settings():
    p = pcm.Pcm(b"\x01\x00" * 100)
    a = pcm.audio_id(p, station=False)
    assert a.startswith("a:") and len(a) == 14
    assert a == pcm.audio_id(pcm.Pcm(b"\x01\x00" * 100), station=False)
    assert a != pcm.audio_id(p, station=True)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_encode_m4a_once(tmp_path):
    import subprocess

    p = pcm.Pcm(b"\x10\x00\xf0\xff" * 12_000)  # 1 s
    pcm.encode_m4a(p, tmp_path / "x.m4a")
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            str(tmp_path / "x.m4a"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(out.stdout)["streams"][0]
    assert stream == {"codec_name": "aac", "sample_rate": "24000", "channels": 1}
    pcm.encode_m4a(p, tmp_path / "y.m4a", station=True)
    assert (tmp_path / "y.m4a").stat().st_size > 0
