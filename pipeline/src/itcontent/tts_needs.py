"""Audio needs (docs/04 § Audio step 1): what the course voices, in which voice, with which IPA overrides.

The pack compiler is the one place that knows what is voiced (texts, items, exercise strings), so it describes each
voiced thing to `Voicing`, which turns it into a `Need`: one audio file of the bundle, made of `NeedLine`s, each
rendered once (`Speech`, keyed by `cache_key`). `content tts` renders the needs the compiler found; `content build`
looks the same needs up in the render cache. A need that can't be voiced carries a `problem` instead of failing the
build (dev packs then leave its audio ID null; `content tts` reports it).

Voices (`content/voices.yaml`): a text line uses its speaker's voice (`narrator`, `announcer`, `ch:…`; `ch:extra` picks
from its pool by FNV-1a 64 of the text ID); items and sound-pair words use `items`; dictation and repeat lines the
narrator; model answers spoken after an answer (recall, sentence building and cloze with `audio_after`) and talk models
are spoken as the learner (`ch:you`, its `m` voice and the model answer, which is the first expansion: docs/03); a
choice's `prompt_it` uses the `audio.speaker` it names; conversation lines the conversation's `with`.

IPA overrides: `content/pronunciation.yaml` (`lexicon`, every context) and a text line's `say` (that line only; it wins
over the lexicon) become `<phoneme alphabet="ipa">` around the word.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from itcontent import audio_pcm
from itcontent.course import Course
from itcontent.tts_azure import Voice, VoiceBook, apply_overrides, billable_characters, cache_key, ssml

ALIGNED_KINDS = frozenset({"word", "name", "number", "foreign"})
# Symbols of Italian IPA transcriptions (Azure's it-IT phone set, docs/04 § Pronunciation): anything else in an
# override is likely a typo, and Azure rejects unknown phones with HTTP 400.
IPA_SYMBOLS = frozenset("abdefgɡijklmnoprstuvwzɛɔʃʒʎɲŋɱʤʧʦʣθ" + "ˈˌːˑ.‿͡")
ITEMS = "items"
NARRATOR = "narrator"
LEARNER = "ch:you"


@dataclass(frozen=True)
class Speech:
    """One utterance to render: the text as written, split into fragments that carry IPA overrides."""

    text: str
    voice: Voice
    parts: tuple[tuple[str, str | None], ...]

    @cached_property
    def ssml(self) -> str:
        return ssml(list(self.parts), self.voice)

    @cached_property
    def key(self) -> str:
        return cache_key(self.voice, self.ssml)

    @property
    def characters(self) -> int:
        return billable_characters(list(self.parts))

    @property
    def overrides(self) -> list[tuple[str, str]]:
        return [(frag, ipa) for frag, ipa in self.parts if ipa is not None]


@dataclass(frozen=True)
class NeedLine:
    speech: Speech
    speaker: str
    label: str  # where it comes from: u02.l1.story#3, w:cornetto, u02.l1.ex13:audioId
    pause_ms: int = 0
    effect: str = ""  # "" or audio_pcm.STATION
    align: tuple[str, ...] | None = None  # text lines: the surfaces of the tokens that get timings
    token_index: tuple[int, ...] = ()  # each aligned token's 0-based index among the line's tokens


@dataclass(frozen=True)
class Need:
    key: str  # text:<id> | item:<id> | sound:<id>:<pair>:<word> | exercise:<id>:<payload slot>
    kind: str  # text | item | sound | exercise
    owner: str  # the text, item or exercise ID
    unit: str
    part: str  # the content file it comes from
    lines: tuple[NeedLine, ...] = ()
    problem: str | None = None  # why it can't be voiced
    notes: tuple[str, ...] = ()  # warnings for `content tts` (a line `say` key that isn't a word of the line)

    @property
    def keys(self) -> list[str]:
        return [ln.speech.key for ln in self.lines]

    def matches(self, wanted: Sequence[str]) -> bool:
        return any(w in (self.key, self.owner) for w in wanted)


@dataclass
class LineSpec:
    """A text line as the compiler describes it."""

    speaker: str
    text: str
    tokens: Sequence[tuple[str, str]]  # (kind, surface) of every token of the line, punctuation included
    label: str
    say: Mapping[str, str] = field(default_factory=dict)
    pause_ms: int = 0


class Voicing:
    """Voices and overrides from `content/voices.yaml` and `content/pronunciation.yaml`."""

    def __init__(self, voices: Mapping[str, Any] | None, lexicon: Mapping[str, Any] | None) -> None:
        self.book = VoiceBook(dict(voices or {}))
        self.lexicon = {str(k): str(v) for k, v in dict(lexicon or {}).items()}

    @classmethod
    def from_course(cls, course: Course) -> Voicing:
        voices = course.singles.get("voices")
        pron = course.singles.get("pronunciation")
        lexicon = pron.data.get("lexicon") if pron is not None and isinstance(pron.data, dict) else None
        return cls(voices.data if voices is not None and isinstance(voices.data, dict) else {}, lexicon)

    def voice(self, speaker: str, text_id: str = "", gender: str = "m") -> tuple[Voice, str]:
        """(voice, effect) of a speaker; raises KeyError when voices.yaml has none."""
        v = self.book.for_speaker(speaker, text_id=text_id, gender=gender)
        return v, audio_pcm.STATION if v.station else ""

    def speech(self, text: str, voice: Voice, say: Mapping[str, str] | None = None) -> Speech:
        overrides = {**self.lexicon, **{str(k): str(v) for k, v in (say or {}).items()}}
        return Speech(text, voice, tuple(apply_overrides(text, overrides)))

    # ------------------------------------------------------------ needs

    def text_need(self, text_id: str, unit: str, part: str, lines: Sequence[LineSpec]) -> Need:
        """A text: its lines in order, joined in PCM; its tokens get timings."""
        out = []
        notes = []
        for spec in lines:
            try:
                voice, effect = self.voice(spec.speaker, text_id)
            except KeyError as exc:
                return Need(f"text:{text_id}", "text", text_id, unit, part, problem=f"{spec.label}: {exc.args[0]}")
            index = tuple(i for i, (kind, _) in enumerate(spec.tokens) if kind in ALIGNED_KINDS)
            speech = self.speech(spec.text, voice, spec.say)
            said = {word.lower() for word, _ in speech.overrides}
            notes += [
                f"{spec.label}: `say` names {k!r}, which isn't a word of the line"
                for k in spec.say
                if k.lower() not in said
            ]
            out.append(
                NeedLine(
                    speech,
                    spec.speaker,
                    spec.label,
                    spec.pause_ms,
                    effect,
                    tuple(spec.tokens[i][1] for i in index),
                    index,
                )
            )
        return Need(f"text:{text_id}", "text", text_id, unit, part, tuple(out), notes=tuple(notes))

    def single(
        self, key: str, kind: str, owner: str, unit: str, part: str, text: str | None, speaker: str, label: str
    ) -> Need:
        """One utterance (an item, a sound-pair word, an exercise string); `text` None means it can't be voiced and
        `label` says why."""
        if text is None:
            return Need(key, kind, owner, unit, part, problem=label)
        if not text.strip():
            return Need(key, kind, owner, unit, part, problem=f"{label}: nothing to say")
        try:
            voice, effect = self.voice(speaker, owner)
        except KeyError as exc:
            return Need(key, kind, owner, unit, part, problem=f"{label}: {exc.args[0]}")
        line = NeedLine(self.speech(text, voice), speaker, label, 0, effect)
        return Need(key, kind, owner, unit, part, (line,))


def item_speech_text(item: Mapping[str, Any], display_form: str | None) -> tuple[str | None, str]:
    """(what TTS says for an item, or None, and why not): `audio_say`, else the display form read aloud. Both
    genders of a noun for people are said one after the other (`l'amico, l'amica`), a chunk's trailing `…` is dropped;
    a form TTS would read letter by letter (`sono nato/a`) needs `audio_say`."""
    if isinstance(item.get("audio_say"), str) and item["audio_say"].strip():
        return str(item["audio_say"]), ""
    shown = display_form or str(item.get("it", ""))
    said = shown.replace(" / ", ", ").replace("…", "").replace("...", "").strip()
    said = said.rstrip(",").strip()
    if "/" in said or "(" in said:
        return None, f"{item.get('id')}: TTS can't read '{shown}' aloud: add `audio_say` to the item"
    return said, ""


def ipa_problem(ipa: str) -> str | None:
    """Why an IPA override looks wrong (symbols outside Italian IPA), or None."""
    odd = sorted({ch for ch in ipa if ch not in IPA_SYMBOLS})
    if not ipa.strip():
        return "empty IPA"
    if odd:
        return f"unexpected symbol(s) {' '.join(odd)} in /{ipa}/: check it against Azure's it-IT phone set"
    if "ˈ" not in ipa and len([ch for ch in ipa if ch in "aeiouɛɔ"]) > 1:
        return f"/{ipa}/ has no stress mark (ˈ before the stressed syllable)"
    return None
