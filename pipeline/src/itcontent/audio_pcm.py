"""PCM helpers for `content tts` and the pack build (docs/04 § Audio, steps 3 and 6–7).

- **Samples:** 16-bit little-endian mono at 24 kHz (Azure's `riff-24khz-16bit-mono-pcm`). Timings are computed from
  sample counts, never from encoded audio: AAC adds encoder priming and padding at every join, so encoded files are
  never concatenated (the read-along would drift).
- **Assembly:** a text's lines are joined in PCM with silence: 300 ms between lines of one speaker, 600 ms on a speaker
  change, plus the earlier line's `pause_ms`. `gaps()` computes the silences, `place()` the lines' positions from sample
  counts alone (so timings and audio IDs need no decoding), `join()` the samples.
- **Station effect** (announcements, `effect: station` in `voices.yaml`): band-pass 300–3400 Hz and a 35 ms echo, in
  pure Python with fixed coefficients, applied to that voice's lines before they are joined. It keeps the sample count
  (timings don't move) and gives the same samples on every machine (no ffmpeg filter whose output could vary).
- **Audio IDs:** `a:<12 hex>` of the sha256 of the assembly manifest (`assembly_digest`): the encode settings and, per
  segment, the sha256 and sample count of its render, the silence before it and its effect. That identifies the
  assembled PCM exactly, so IDs depend neither on the ffmpeg build nor on decoding the cache.
- **FLAC** (the render cache) and **AAC** (the bundle) go through ffmpeg; the settings are pinned in `ENCODE`.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 24_000
SAMPLE_WIDTH = 2  # 16-bit
CHANNELS = 1
SAME_SPEAKER_GAP_MS = 300
SPEAKER_CHANGE_GAP_MS = 600
STATION = "station-v1"  # the effect's version: part of every audio ID that uses it


@dataclass(frozen=True)
class EncodeSettings:
    """The one AAC encode per text (ADR-17: AAC-LC, 24 kHz mono, 48 kbps; 40 kbps if Units 0–1 project above budget).

    `-use_editlist 1` writes the MP4 edit list that tells players to skip the encoder's 1,024 priming samples, so
    media time 0 is the first sample of the PCM (docs/09 § Encoder delay); bitexact flags keep the bytes the same for
    the same ffmpeg build."""

    codec: str = "aac"
    profile: str = "aac_low"
    bitrate: str = "48k"
    sample_rate: int = SAMPLE_RATE
    channels: int = CHANNELS

    @property
    def bits_per_second(self) -> int:
        return int(self.bitrate.rstrip("k")) * 1000

    def canonical(self) -> str:
        return f"{self.codec}|{self.profile}|{self.bitrate}|{self.sample_rate}|{self.channels}|editlist"

    def ffmpeg_args(self) -> list[str]:
        return [
            "-c:a",
            self.codec,
            "-profile:a",
            self.profile,
            "-b:a",
            self.bitrate,
            "-ar",
            str(self.sample_rate),
            "-ac",
            str(self.channels),
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-flags:a",
            "+bitexact",
            "-use_editlist",
            "1",
            "-movflags",
            "+faststart",
        ]


ENCODE = EncodeSettings()
FLAC_ARGS = ["-c:a", "flac", "-compression_level", "8", "-fflags", "+bitexact", "-flags:a", "+bitexact"]


@dataclass(frozen=True)
class Pcm:
    """Raw 16-bit little-endian mono samples at 24 kHz."""

    frames: bytes

    @property
    def samples(self) -> int:
        return len(self.frames) // SAMPLE_WIDTH

    @property
    def duration_ms(self) -> int:
        return samples_to_ms(self.samples)

    def sha256(self) -> str:
        return hashlib.sha256(self.frames).hexdigest()


def samples_to_ms(samples: int) -> int:
    return round(samples * 1000 / SAMPLE_RATE)


def ms_to_samples(ms: int) -> int:
    return round(ms * SAMPLE_RATE / 1000)


def silence(ms: int) -> Pcm:
    return Pcm(b"\x00\x00" * ms_to_samples(ms))


# ---------------------------------------------------------------- WAV


def _check_format(w: wave.Wave_read, where: str) -> None:
    if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE):
        raise ValueError(
            f"{where}: expected {SAMPLE_RATE} Hz 16-bit mono (riff-24khz-16bit-mono-pcm), got "
            f"{w.getframerate()} Hz, {8 * w.getsampwidth()}-bit, {w.getnchannels()} channel(s)"
        )


def read_wav(path: Path) -> Pcm:
    with wave.open(str(path), "rb") as w:
        _check_format(w, str(path))
        return Pcm(w.readframes(w.getnframes()))


def read_wav_bytes(data: bytes, where: str = "WAV") -> Pcm:
    with wave.open(io.BytesIO(data), "rb") as w:
        _check_format(w, where)
        return Pcm(w.readframes(w.getnframes()))


def wav_bytes(pcm: Pcm) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.frames)
    return buf.getvalue()


def write_wav(pcm: Pcm, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav_bytes(pcm))


# ---------------------------------------------------------------- assembly


@dataclass(frozen=True)
class Segment:
    """A piece of a text: one line's audio with its speaker and any extra pause after it."""

    pcm: Pcm
    speaker: str
    pause_ms: int = 0


@dataclass(frozen=True)
class Placed:
    start_ms: int
    end_ms: int
    offset_samples: int


def gaps(speakers: Sequence[str], pauses: Sequence[int]) -> list[int]:
    """The silence before each line (ms): none before the first, then 300 ms after a line of the same speaker or
    600 ms on a speaker change, plus the earlier line's `pause_ms` (docs/04 § Audio step 6)."""
    out = []
    for i, speaker in enumerate(speakers):
        if i == 0:
            out.append(0)
        else:
            base = SAME_SPEAKER_GAP_MS if speakers[i - 1] == speaker else SPEAKER_CHANGE_GAP_MS
            out.append(base + int(pauses[i - 1]))
    return out


def place(sample_counts: Sequence[int], gap_ms: Sequence[int]) -> tuple[list[Placed], int]:
    """Each segment's position from sample counts alone, and the total sample count."""
    placed: list[Placed] = []
    offset = 0
    for n, gap in zip(sample_counts, gap_ms, strict=True):
        offset += ms_to_samples(gap)
        placed.append(Placed(samples_to_ms(offset), samples_to_ms(offset + n), offset))
        offset += n
    return placed, offset


def join(pcms: Sequence[Pcm], gap_ms: Sequence[int]) -> Pcm:
    parts: list[bytes] = []
    for p, gap in zip(pcms, gap_ms, strict=True):
        parts.append(silence(gap).frames)
        parts.append(p.frames)
    return Pcm(b"".join(parts))


def assemble(segments: list[Segment]) -> tuple[Pcm, list[Placed]]:
    """Join lines in PCM with the gaps of `gaps()`. Returns the joined audio and each line's placement."""
    g = gaps([s.speaker for s in segments], [s.pause_ms for s in segments])
    placed, _ = place([s.pcm.samples for s in segments], g)
    return join([s.pcm for s in segments], g), placed


@dataclass(frozen=True)
class SegmentRef:
    """What an audio ID is computed from, per segment: its render's samples (by hash and count), the silence before
    it and the effect applied to it."""

    pcm_sha256: str
    samples: int
    gap_ms: int
    effect: str = ""


def assembly_digest(segments: Sequence[SegmentRef], settings: EncodeSettings = ENCODE) -> str:
    """sha256 (64 hex) of the assembly manifest: the encode settings and every segment. `audio.sha256` stores it."""
    manifest = {
        "encode": settings.canonical(),
        "segments": [[s.pcm_sha256, s.samples, s.gap_ms, s.effect] for s in segments],
    }
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def audio_id(digest: str) -> str:
    """`a:<12 hex>` from an assembly digest (docs/03 § IDs)."""
    return "a:" + digest[:12]


# ---------------------------------------------------------------- the station effect


# RBJ cookbook biquads at 24 kHz, Q = 1/√2, normalised by a0: (b0, b1, b2, a1, a2). Literal values so every machine
# computes the same samples (derived once with math.cos/sin; see the module docstring).
_HIGHPASS_300 = (0.9459768560027901, -1.8919537120055803, 0.9459768560027901, -1.8890330793945247, 0.8948743446166356)
_LOWPASS_3400 = (
    0.11961070846016206,
    0.23922141692032411,
    0.11961070846016206,
    -0.8122751400875438,
    0.29071797392819193,
)
_ECHO_SAMPLES = 840  # 35 ms
_ECHO_DECAY = 0.25
_STATION_GAIN = 0.8


def _biquad(x: list[float], c: tuple[float, float, float, float, float]) -> list[float]:
    b0, b1, b2, a1, a2 = c
    x1 = x2 = y1 = y2 = 0.0
    out = []
    for v in x:
        y = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1 = x1, v
        y2, y1 = y1, y
        out.append(y)
    return out


def station_effect(pcm: Pcm) -> Pcm:
    """A station or shop loudspeaker: band-pass 300–3400 Hz, then one 35 ms echo at 25%. Same length."""
    import array

    samples = array.array("h")
    samples.frombytes(pcm.frames)
    filtered = _biquad(_biquad([float(v) for v in samples], _HIGHPASS_300), _LOWPASS_3400)
    out = array.array("h")
    for i, v in enumerate(filtered):
        echo = filtered[i - _ECHO_SAMPLES] * _ECHO_DECAY if i >= _ECHO_SAMPLES else 0.0
        y = round((v + echo) * _STATION_GAIN)
        out.append(32767 if y > 32767 else -32768 if y < -32768 else y)
    return Pcm(out.tobytes())


# ---------------------------------------------------------------- ffmpeg: FLAC cache, AAC encode


def ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("ffmpeg is not installed (docs/02 § Dependencies)")
    return path


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _raw_input() -> list[str]:
    return ["-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "-i", "pipe:0"]


def _run(cmd: list[str], data: bytes | None = None) -> bytes:
    try:
        r = subprocess.run(cmd, input=data, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg failed: {exc.stderr.decode('utf-8', 'replace')[-500:]}") from exc
    return r.stdout


def write_flac(pcm: Pcm, path: Path) -> None:
    """Lossless and sample-exact: `read_flac` gives back the same samples."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", *_raw_input(), *FLAC_ARGS]
    _run([*cmd, "-f", "flac", str(tmp)], pcm.frames)
    tmp.replace(path)


def read_flac(path: Path) -> Pcm:
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-i", str(path)]
    out = _run([*cmd, "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "pipe:1"])
    return Pcm(out)


def encode_m4a(pcm: Pcm, out: Path, settings: EncodeSettings = ENCODE) -> None:
    """Encode once to AAC-LC `.m4a` (docs/04 § Audio step 7), through a temporary file and a rename."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", *_raw_input(), *settings.ffmpeg_args()]
    _run([*cmd, "-f", "ipod", str(tmp)], pcm.frames)
    tmp.replace(out)


def estimated_m4a_bytes(duration_ms: int, settings: EncodeSettings = ENCODE) -> int:
    """What a file of this length will take at most: the bitrate plus about 1 KB of container (ffmpeg 6.1). Silence
    and synthetic audio come out smaller, so the projection prefers the sizes of files already encoded."""
    return round(duration_ms * settings.bits_per_second / 8000) + 1000
