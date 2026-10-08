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


def test_audio_id_is_the_assembly_manifest_hash():
    """The ID covers each segment's samples (hash and count), the silence before it, its effect and the encode
    settings; it is computed from metadata alone, so it doesn't depend on decoding or on the ffmpeg build."""
    seg = pcm.SegmentRef("a" * 64, 24_000, 0)
    base = pcm.assembly_digest([seg])
    assert len(base) == 64 and base == pcm.assembly_digest([pcm.SegmentRef("a" * 64, 24_000, 0)])
    aid = pcm.audio_id(base)
    assert aid == "a:" + base[:12] and len(aid) == 14
    variants = [
        [pcm.SegmentRef("b" * 64, 24_000, 0)],
        [pcm.SegmentRef("a" * 64, 24_001, 0)],
        [pcm.SegmentRef("a" * 64, 24_000, 300)],
        [pcm.SegmentRef("a" * 64, 24_000, 0, pcm.STATION)],
        [seg, seg],
    ]
    assert len({base, *(pcm.assembly_digest(v) for v in variants)}) == 6
    assert base != pcm.assembly_digest([seg], pcm.EncodeSettings(bitrate="40k"))


def test_gaps_and_placement_agree_with_assembly():
    a = pcm.Pcm(b"\x01\x00" * 24_000)
    b = pcm.Pcm(b"\x02\x00" * 12_000)
    segments = [pcm.Segment(a, "ch:giulia"), pcm.Segment(b, "ch:giulia", pause_ms=200), pcm.Segment(a, "ch:marco")]
    g = pcm.gaps([s.speaker for s in segments], [s.pause_ms for s in segments])
    assert g == [0, 300, 800]
    placed, total = pcm.place([s.pcm.samples for s in segments], g)
    joined, assembled = pcm.assemble(segments)
    assert placed == assembled and total == joined.samples
    assert joined.frames[placed[1].offset_samples * 2 : placed[1].offset_samples * 2 + 2] == b"\x02\x00"


def test_station_effect_keeps_length_and_band_passes():
    import math

    def tone(hz: float) -> pcm.Pcm:
        import array

        return pcm.Pcm(
            array.array("h", (round(8000 * math.sin(2 * math.pi * hz * i / 24_000)) for i in range(24_000))).tobytes()
        )

    def energy(p: pcm.Pcm) -> float:
        import array

        a = array.array("h")
        a.frombytes(p.frames[4800:])  # after the filters settle
        return sum(v * v for v in a) / len(a)

    low, mid, high = tone(80), tone(1000), tone(8000)
    for t in (low, mid, high):
        out = pcm.station_effect(t)
        assert out.samples == t.samples
    assert energy(pcm.station_effect(mid)) > 0.4 * energy(mid)
    assert energy(pcm.station_effect(low)) < 0.1 * energy(low)
    assert energy(pcm.station_effect(high)) < 0.1 * energy(high)
    assert pcm.station_effect(mid) == pcm.station_effect(mid)  # pure arithmetic: the same samples everywhere


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


@needs_ffmpeg
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
            "stream=codec_name,profile,sample_rate,channels",
            "-of",
            "json",
            str(tmp_path / "x.m4a"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(out.stdout)["streams"][0]
    assert stream == {"codec_name": "aac", "profile": "LC", "sample_rate": "24000", "channels": 1}
    pcm.encode_m4a(p, tmp_path / "y.m4a")
    assert (tmp_path / "x.m4a").read_bytes() == (tmp_path / "y.m4a").read_bytes()  # bitexact: same bytes again
    assert not list(tmp_path.glob("*.tmp"))


def _mp4_box(data: bytes, name: bytes) -> bytes:
    """The payload of the first box with this name (depth-first through the container boxes)."""
    containers = {b"moov", b"trak", b"edts", b"mdia", b"minf", b"stbl"}

    def walk(buf: bytes) -> bytes | None:
        i = 0
        while i + 8 <= len(buf):
            size = int.from_bytes(buf[i : i + 4], "big")
            kind = buf[i + 4 : i + 8]
            body = buf[i + 8 : i + size]
            if kind == name:
                return body
            if kind in containers and (found := walk(body)) is not None:
                return found
            i += size if size else len(buf)
        return None

    found = walk(data)
    assert found is not None, f"no {name!r} box"
    return found


@needs_ffmpeg
def test_encoder_delay_is_in_the_edit_list(tmp_path):
    """docs/09 § Encoder delay: AAC primes 1,024 samples. The MP4 edit list must tell the player to skip them, so a
    sound at sample n of the PCM plays at media time n / 24 kHz. Decoding with the edit list puts the onset where it
    is in the PCM (well within the 50 ms read-along tolerance); ignoring it shifts it by ~43 ms."""
    import array
    import math
    import subprocess

    onset = 12_000  # 500 ms
    a = array.array("h", [0] * 36_000)
    for i in range(onset, onset + 2_400):
        a[i] = round(12_000 * math.sin(2 * math.pi * 440 * (i - onset) / 24_000))
    pcm.encode_m4a(pcm.Pcm(a.tobytes()), tmp_path / "t.m4a")
    data = (tmp_path / "t.m4a").read_bytes()

    elst = _mp4_box(data, b"elst")
    version = elst[0]
    count = int.from_bytes(elst[4:8], "big")
    assert count == 1
    width = 8 if version == 1 else 4
    duration = int.from_bytes(elst[8 : 8 + width], "big")
    media_time = int.from_bytes(elst[8 + width : 8 + 2 * width], "big", signed=True)
    assert media_time == 1024  # the priming samples, in the 24 kHz media timescale
    mvhd = _mp4_box(data, b"mvhd")
    timescale = int.from_bytes(mvhd[12:16] if mvhd[0] == 0 else mvhd[20:24], "big")
    assert round(duration * 1000 / timescale) == 1500  # exactly the PCM's length

    def decoded_onset(*flags: str) -> float:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", *flags, "-i", str(tmp_path / "t.m4a"), "-f", "s16le", "-ac", "1", "-"],
            capture_output=True,
            check=True,
        ).stdout
        s = array.array("h")
        s.frombytes(raw)
        first = next(i for i, v in enumerate(s) if abs(v) > 2_000)
        return (first - onset) / 24

    assert abs(decoded_onset()) < 2  # ms: the edit list is honoured
    assert decoded_onset("-ignore_editlist", "1") > 40  # what a player that ignores it would do


@needs_ffmpeg
def test_flac_round_trip_is_sample_exact(tmp_path):
    import array

    a = array.array("h", ((i * 7919) % 65536 - 32768 for i in range(24_000)))
    p = pcm.Pcm(a.tobytes())
    pcm.write_flac(p, tmp_path / "r.flac")
    assert pcm.read_flac(tmp_path / "r.flac") == p


# ---------------------------------------------------------------- overrides and alignment details


def test_overrides_reach_elided_and_quoted_words():
    lex = {"ancora": "anˈkoːra", "po'": "pɔ"}
    assert apply_overrides("l'ancora", lex) == [("l'", None), ("ancora", "anˈkoːra")]
    assert apply_overrides("'ancora'", lex) == [("'", None), ("ancora", "anˈkoːra"), ("'", None)]
    assert apply_overrides("un po' di latte", lex) == [("un ", None), ("po'", "pɔ"), (" di latte", None)]
    assert apply_overrides("quant'è", lex) == [("quant'è", None)]
    assert apply_overrides("Ancora!", {}) == [("Ancora!", None)]
    s = ssml(apply_overrides("l'ancora", lex), Voice("it-IT-ElsaNeural"))
    assert "l'<phoneme" in s or "l&apos;<phoneme" in s


def test_align_tolerates_quotes_but_not_other_words():
    bounds = [wb("Si", 0, 100), wb("dice", 120, 200), wb('"', 320, 0), wb("cornetto", 330, 400), wb('".', 730, 0)]
    assert align(["Si", "dice", "cornetto"], bounds, "x#6") == [(0, 100), (120, 320), (330, 730)]
    assert align(["ancora"], [wb("'ancora'", 0, 300)], "x") == [(0, 300)]
    assert align(["po'"], [wb("po", 0, 120)], "x") == [(0, 120)]
    with pytest.raises(AlignmentError, match="x#2"):
        align(["un'", "amica"], [wb("un'amico", 0, 300)], "x#2")


def test_billable_characters_count_text_and_ipa():
    from itcontent.tts_azure import billable_characters

    assert billable_characters([("Ancora", "anˈkoːra"), (" un caffè?", None)]) == 6 + 8 + 10
