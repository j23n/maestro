"""The TTS render cache (docs/04 § Audio step 3): every rendered utterance, by cache key.

Layout: `<root>/<key[:2]>/<key>.flac` (the render, lossless and sample-exact; Git LFS under
`content-build/tts-cache/`) next to `<key>.json` (plain Git, small and diffable). Mock renders are kept as `.wav`
instead: synthetic tones compress ten times better under Git's zlib than as FLAC, and reading them needs no ffmpeg.

```json
{"boundaries": [{"duration_ms": 400, "offset_ms": 50, "text": "Buongiorno"}, …], "format": 1, "key": "<64 hex>",
 "output_format": "riff-24khz-16bit-mono-pcm", "pcm_sha256": "<64 hex>", "pitch": "0%", "provider": "azure",
 "rate": "0%", "samples": 31200, "sample_rate": 24000, "ssml": "<speak …>", "style": "", "text": "Buongiorno!",
 "voice": "it-IT-IsabellaNeural"}
```

The metadata is enough to compute a text's audio ID, timings and duration (`audio_assets`); the FLAC is decoded only
when a file has to be encoded. A render is never overwritten: the key covers everything that changes the audio.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from itcontent import audio_pcm
from itcontent.tts_azure import OUTPUT_FORMAT, Voice, WordBoundary

CACHE_FORMAT = 1


@dataclass(frozen=True)
class RenderMeta:
    key: str
    provider: str  # azure | mock
    voice: str
    rate: str
    pitch: str
    style: str
    ssml: str
    text: str
    samples: int
    pcm_sha256: str
    boundaries: tuple[WordBoundary, ...]
    output_format: str = OUTPUT_FORMAT

    @property
    def duration_ms(self) -> int:
        return audio_pcm.samples_to_ms(self.samples)

    def to_json(self) -> dict[str, Any]:
        return {
            "format": CACHE_FORMAT,
            "key": self.key,
            "provider": self.provider,
            "voice": self.voice,
            "rate": self.rate,
            "pitch": self.pitch,
            "style": self.style,
            "ssml": self.ssml,
            "text": self.text,
            "output_format": self.output_format,
            "sample_rate": audio_pcm.SAMPLE_RATE,
            "samples": self.samples,
            "pcm_sha256": self.pcm_sha256,
            "boundaries": [
                {"text": b.text, "offset_ms": b.offset_ms, "duration_ms": b.duration_ms} for b in self.boundaries
            ],
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> RenderMeta:
        if d.get("format") != CACHE_FORMAT or d.get("sample_rate") != audio_pcm.SAMPLE_RATE:
            raise ValueError(f"render {d.get('key')}: unknown cache format {d.get('format')}")
        return cls(
            key=str(d["key"]),
            provider=str(d.get("provider", "azure")),
            voice=str(d["voice"]),
            rate=str(d.get("rate", "0%")),
            pitch=str(d.get("pitch", "0%")),
            style=str(d.get("style", "")),
            ssml=str(d["ssml"]),
            text=str(d.get("text", "")),
            samples=int(d["samples"]),
            pcm_sha256=str(d["pcm_sha256"]),
            boundaries=tuple(
                WordBoundary(str(b["text"]), int(b["offset_ms"]), int(b["duration_ms"]))
                for b in d.get("boundaries", ())
            ),
            output_format=str(d.get("output_format", OUTPUT_FORMAT)),
        )


class RenderCache:
    """One cache directory. `name` says where its renders come from in messages (`azure`, `mock`, `fixture`)."""

    def __init__(self, root: Path, name: str = "azure") -> None:
        self.root = root
        self.name = name
        self._meta: dict[str, RenderMeta] = {}

    def __repr__(self) -> str:
        return f"RenderCache({self.root}, {self.name!r})"

    def _base(self, key: str) -> Path:
        return self.root / key[:2] / key

    def meta(self, key: str) -> RenderMeta | None:
        """The render's metadata, or None. Found metadata is kept (a render never changes); misses aren't, so a render
        another process or cache object adds is seen."""
        if key not in self._meta:
            path = self._base(key).with_suffix(".json")
            if not path.is_file():
                return None
            found = RenderMeta.from_json(json.loads(path.read_text(encoding="utf-8")))
            if found.key != key:
                raise ValueError(f"{path}: written for key {found.key}")
            self._meta[key] = found
        return self._meta[key]

    def has(self, key: str) -> bool:
        return self.meta(key) is not None

    def audio_path(self, key: str) -> Path:
        base = self._base(key)
        wav = base.with_suffix(".wav")
        return wav if wav.is_file() else base.with_suffix(".flac")

    def pcm(self, key: str) -> audio_pcm.Pcm:
        """The render's samples, checked against the hash in its metadata (an LFS pointer or a damaged file fails)."""
        meta = self.meta(key)
        if meta is None:
            raise KeyError(f"no render {key} in {self.root}")
        path = self.audio_path(key)
        if not path.is_file():
            raise FileNotFoundError(f"{path} is missing (run `git lfs pull`)")
        if path.stat().st_size < 200 and path.read_bytes().startswith(b"version https://git-lfs"):
            raise FileNotFoundError(f"{path} is a Git LFS pointer: run `git lfs pull`")
        pcm = audio_pcm.read_wav(path) if path.suffix == ".wav" else audio_pcm.read_flac(path)
        if pcm.sha256() != meta.pcm_sha256 or pcm.samples != meta.samples:
            raise ValueError(f"{path}: the samples don't match its metadata (damaged render)")
        return pcm

    def put(
        self,
        key: str,
        pcm: audio_pcm.Pcm,
        boundaries: list[WordBoundary],
        *,
        voice: Voice,
        ssml: str,
        text: str,
        provider: str,
    ) -> RenderMeta:
        meta = RenderMeta(
            key=key,
            provider=provider,
            voice=voice.name,
            rate=voice.rate,
            pitch=voice.pitch,
            style=voice.style,
            ssml=ssml,
            text=text,
            samples=pcm.samples,
            pcm_sha256=pcm.sha256(),
            boundaries=tuple(boundaries),
        )
        base = self._base(key)
        if provider == "mock":
            audio_pcm.write_wav(pcm, base.with_suffix(".wav"))
        else:
            audio_pcm.write_flac(pcm, base.with_suffix(".flac"))
        tmp = base.with_name(base.name + ".json.tmp")
        tmp.write_text(json.dumps(meta.to_json(), ensure_ascii=False, sort_keys=True, indent=1) + "\n", "utf-8")
        tmp.replace(base.with_suffix(".json"))
        self._meta[key] = meta
        return meta

    def keys(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.stem for p in self.root.glob("??/*.json"))
