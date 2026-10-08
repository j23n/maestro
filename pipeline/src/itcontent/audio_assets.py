"""From renders to the bundle's audio (docs/04 § Audio steps 5–7, § Pack build › Audio).

`AudioResolver.resolve(need)` looks every line of a need up in the render caches (in order: for dev builds the Azure
cache, then the mock cache), aligns text lines' word boundaries to their tokens, places the lines with their gaps and
computes the audio ID from the assembly manifest, all from the renders' metadata (no decoding). It returns `Resolved`
(the ID, duration, each line's span and each token's span, in ms from the start of the file) or `Missing` (why not).

`encode()` writes each resolved audio file once (`<12 hex>.m4a`) into the encode cache (`build/audio/`, a build
output): it decodes the renders, applies the station effect to station lines, joins them with silence and encodes the
whole text in one go. Files already there are reused: the name is a hash of exactly what they contain.

`AudioPlan` is what the pack compiler talks to: it records every need and answers with the resolution (or nothing
when the build has no resolver, as when `content tts` only collects the needs).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from itcontent import audio_pcm
from itcontent.audio_pcm import ENCODE, EncodeSettings, Pcm, SegmentRef
from itcontent.tts_azure import AlignmentError, align
from itcontent.tts_cache import RenderCache, RenderMeta
from itcontent.tts_needs import Need


@dataclass(frozen=True)
class LineAudio:
    start_ms: int
    end_ms: int
    tokens: dict[int, tuple[int, int]]  # 0-based token index in the line → (start_ms, end_ms) in the file


@dataclass(frozen=True)
class Resolved:
    need: Need
    audio_id: str
    digest: str  # audio.sha256
    duration_ms: int
    voice: str  # the voices, in order of appearance (mock renders say so)
    lines: tuple[LineAudio, ...]
    renders: tuple[tuple[RenderCache, RenderMeta], ...]
    gaps: tuple[int, ...]

    @property
    def file(self) -> str:
        return self.audio_id[2:] + ".m4a"

    @property
    def providers(self) -> set[str]:
        return {meta.provider for _, meta in self.renders}

    def row(self) -> tuple[str, str, int, str, str]:
        """A row of the `audio` table."""
        return (self.audio_id, self.file, self.duration_ms, self.voice, self.digest)


@dataclass(frozen=True)
class Missing:
    need: Need
    reason: str  # not-voiceable | not-rendered | alignment
    detail: str


class AudioResolver:
    def __init__(
        self, caches: Iterable[RenderCache], encode_dir: Path | None = None, settings: EncodeSettings = ENCODE
    ) -> None:
        self.caches = list(caches)
        self.encode_dir = encode_dir
        self.settings = settings
        self._results: dict[str, Resolved | Missing] = {}

    def find(self, key: str) -> tuple[RenderCache, RenderMeta] | None:
        for cache in self.caches:
            meta = cache.meta(key)
            if meta is not None:
                return cache, meta
        return None

    def resolve(self, need: Need) -> Resolved | Missing:
        if need.key not in self._results:
            self._results[need.key] = self._resolve(need)
        return self._results[need.key]

    def _resolve(self, need: Need) -> Resolved | Missing:
        if need.problem is not None:
            return Missing(need, "not-voiceable", need.problem)
        renders = []
        for line in need.lines:
            found = self.find(line.speech.key)
            if found is None:
                return Missing(need, "not-rendered", f"{line.label}: not rendered (`content tts`)")
            renders.append(found)
        gap_ms = audio_pcm.gaps([ln.speaker for ln in need.lines], [ln.pause_ms for ln in need.lines])
        placed, total = audio_pcm.place([m.samples for _, m in renders], gap_ms)
        lines = []
        for line, (_, meta), where in zip(need.lines, renders, placed, strict=True):
            tokens: dict[int, tuple[int, int]] = {}
            if line.align is not None:
                try:
                    spans = align(list(line.align), list(meta.boundaries), line.label)
                except AlignmentError as exc:
                    return Missing(need, "alignment", str(exc))
                for index, (start, end) in zip(line.token_index, spans, strict=True):
                    s = min(where.start_ms + start, where.end_ms)
                    tokens[index] = (s, max(s, min(where.start_ms + end, where.end_ms)))
            lines.append(LineAudio(where.start_ms, where.end_ms, tokens))
        refs = [
            SegmentRef(meta.pcm_sha256, meta.samples, gap, line.effect)
            for line, (_, meta), gap in zip(need.lines, renders, gap_ms, strict=True)
        ]
        digest = audio_pcm.assembly_digest(refs, self.settings)
        voices: list[str] = []
        for _, meta in renders:
            name = f"mock:{meta.voice}" if meta.provider == "mock" else meta.voice
            if name not in voices:
                voices.append(name)
        return Resolved(
            need,
            audio_pcm.audio_id(digest),
            digest,
            audio_pcm.samples_to_ms(total),
            ", ".join(voices),
            tuple(lines),
            tuple(renders),
            tuple(gap_ms),
        )

    @property
    def results(self) -> dict[str, Resolved | Missing]:
        return dict(self._results)

    def resolved(self) -> list[Resolved]:
        return [r for r in self._results.values() if isinstance(r, Resolved)]

    def missing(self) -> list[Missing]:
        return [r for r in self._results.values() if isinstance(r, Missing)]

    # ------------------------------------------------------------ files

    def pcm(self, r: Resolved) -> Pcm:
        """The assembled samples of a resolved need: renders decoded, effects applied, joined with silence."""
        parts = []
        for line, (cache, meta) in zip(r.need.lines, r.renders, strict=True):
            p = cache.pcm(meta.key)
            if line.effect == audio_pcm.STATION:
                p = audio_pcm.station_effect(p)
            parts.append(p)
        return audio_pcm.join(parts, list(r.gaps))

    def encoded_path(self, r: Resolved) -> Path | None:
        return self.encode_dir / r.file if self.encode_dir is not None else None

    def encode(self, items: Iterable[Resolved], *, also_in: Path | None = None) -> tuple[dict[str, Path], list[str]]:
        """Encode each audio file once (`also_in`: a folder whose files count as encoded, like the bundle's `Audio/`).
        Returns (file name → path, problems); a problem leaves that file out."""
        out: dict[str, Path] = {}
        problems: list[str] = []
        for r in sorted({r.audio_id: r for r in items}.values(), key=lambda r: r.audio_id):
            if also_in is not None and (also_in / r.file).is_file():
                out[r.file] = also_in / r.file
                continue
            path = self.encoded_path(r)
            if path is None:
                problems.append(f"{r.file}: no encode folder")
                continue
            if not path.is_file():
                try:
                    audio_pcm.encode_m4a(self.pcm(r), path, self.settings)
                except (OSError, RuntimeError, ValueError, KeyError) as exc:
                    problems.append(f"{r.file} ({r.need.owner}): {exc}")
                    continue
            out[r.file] = path
        return out, problems


@dataclass
class AudioPlan:
    """The needs one compile met, and their resolution (None: collect only)."""

    resolver: AudioResolver | None = None
    needs: dict[str, Need] = field(default_factory=dict)

    def add(self, need: Need) -> Resolved | None:
        if need.key in self.needs and self.needs[need.key] != need:
            raise ValueError(f"audio need {need.key} is described twice, differently")
        self.needs[need.key] = need
        if self.resolver is None:
            return None
        r = self.resolver.resolve(need)
        return r if isinstance(r, Resolved) else None

    def audio_id(self, need: Need) -> str | None:
        r = self.add(need)
        return r.audio_id if r else None

    def result(self, need: Need) -> Resolved | Missing | None:
        return self.resolver.resolve(need) if self.resolver is not None else None
