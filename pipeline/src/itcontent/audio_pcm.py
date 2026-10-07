"""PCM WAV helpers for `content tts` (docs/04 § Audio, steps 6–7): read and write 16-bit mono WAV, silence, joins
with exact sample counts, and the one AAC encode per text with ffmpeg.

Timings are computed from sample counts, never from encoded audio: AAC adds encoder priming and padding at every
join, so encoded files are never concatenated (the read-along would drift).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 24_000
SAMPLE_WIDTH = 2  # 16-bit
CHANNELS = 1
AAC_BITRATE = "48k"  # ADR-17: AAC-LC, 24 kHz mono, 48 kbps (40 kbps if Units 0–1 project above budget)
STATION_FILTER = "highpass=f=300,lowpass=f=3400,aecho=0.8:0.5:35:0.25"  # announcements (docs/06 §3)


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


def samples_to_ms(samples: int) -> int:
    return round(samples * 1000 / SAMPLE_RATE)


def ms_to_samples(ms: int) -> int:
    return round(ms * SAMPLE_RATE / 1000)


def silence(ms: int) -> Pcm:
    return Pcm(b"\x00\x00" * ms_to_samples(ms))


def read_wav(path: Path) -> Pcm:
    with wave.open(str(path), "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE):
            raise ValueError(
                f"{path}: expected {SAMPLE_RATE} Hz 16-bit mono (riff-24khz-16bit-mono-pcm), got "
                f"{w.getframerate()} Hz, {8 * w.getsampwidth()}-bit, {w.getnchannels()} channel(s)"
            )
        return Pcm(w.readframes(w.getnframes()))


def write_wav(pcm: Pcm, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.frames)


def wav_bytes_sha256(pcm: Pcm) -> str:
    return hashlib.sha256(pcm.frames).hexdigest()


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


def assemble(
    segments: list[Segment], same_speaker_gap_ms: int = 300, speaker_change_gap_ms: int = 600
) -> tuple[Pcm, list[Placed]]:
    """Join lines in PCM: 300 ms between lines of one speaker, 600 ms on a speaker change, plus each line's
    `pause_ms` (docs/04 § Audio step 6). Returns the joined audio and each line's placement."""
    parts: list[bytes] = []
    placed: list[Placed] = []
    offset = 0
    for i, seg in enumerate(segments):
        if i > 0:
            prev = segments[i - 1]
            gap = (same_speaker_gap_ms if prev.speaker == seg.speaker else speaker_change_gap_ms) + prev.pause_ms
            pad = silence(gap)
            parts.append(pad.frames)
            offset += pad.samples
        placed.append(Placed(samples_to_ms(offset), samples_to_ms(offset + seg.pcm.samples), offset))
        parts.append(seg.pcm.frames)
        offset += seg.pcm.samples
    return Pcm(b"".join(parts)), placed


def ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("ffmpeg is not installed (docs/02 § Dependencies)")
    return path


def encode_m4a(
    pcm: Pcm, out: Path, *, station: bool = False, bitrate: str = AAC_BITRATE, workdir: Path | None = None
) -> None:
    """Encode once to AAC-LC .m4a, 24 kHz mono (docs/04 § Audio step 7). `station` adds the announcement effect."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = (workdir or out.parent) / (out.stem + ".src.wav")
    write_wav(pcm, tmp)
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(tmp)]
    if station:
        cmd += ["-af", STATION_FILTER]
    cmd += [
        "-c:a",
        "aac",
        "-b:a",
        bitrate,
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        "-map_metadata",
        "-1",
        "-fflags",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-movflags",
        "+faststart",
        str(out),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        tmp.unlink(missing_ok=True)


def audio_id(pcm: Pcm, *, station: bool, bitrate: str = AAC_BITRATE) -> str:
    """`a:<12 hex>` from the assembled PCM and the encode settings, so IDs don't depend on the ffmpeg build."""
    h = hashlib.sha256(pcm.frames + f"|aac|{bitrate}|{SAMPLE_RATE}|mono|station={station}".encode())
    return "a:" + h.hexdigest()[:12]
