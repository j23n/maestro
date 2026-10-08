"""The mock TTS provider (`content tts --provider mock`): deterministic synthetic audio, offline, no keys.

It takes the same SSML as Azure and answers like Azure's batch synthesis: a 24 kHz 16-bit mono WAV per input and its
word boundaries (`Text`, `AudioOffset`, `Duration` in ms), with punctuation as separate zero-length boundaries and
elided forms as one word (`quant'è`), so alignment, assembly, encoding and the pack build run end to end without the
network. Each word is a tone burst whose length follows its letters (and the voice's `rate`) and whose pitch follows
the voice (and its `pitch`), so speakers sound different; integer arithmetic only, so every machine renders the same
samples. Mock renders go to their own cache (`build/tts-mock-cache/`), never to the Azure cache.
"""

from __future__ import annotations

import array
import hashlib
import html
import re

from itcontent import audio_pcm
from itcontent.tts_azure import SynthesisResult, WordBoundary

LEAD_MS = 60
TAIL_MS = 120
WORD_GAP_MS = 50
COMMA_PAUSE_MS = 150
STOP_PAUSE_MS = 250
AMPLITUDE = 4000
RAMP_MS = 8

_TAG = re.compile(r"<[^>]+>")
_ATTR = re.compile(r'(\w+)="([^"]*)"')


def _percent(value: str) -> int:
    m = re.fullmatch(r"\s*([+-]?\d+)(?:\.\d+)?%\s*", value or "")
    return int(m.group(1)) if m else 0


def parse_ssml(ssml: str) -> tuple[str, str, int, int]:
    """(voice name, spoken text, rate %, pitch %) of one SSML input."""
    voice = ""
    rate = pitch = 0
    for tag in re.findall(r"<(voice|prosody)\b([^>]*)>", ssml):
        attrs = dict(_ATTR.findall(tag[1]))
        if tag[0] == "voice":
            voice = attrs.get("name", voice)
        else:
            rate = _percent(attrs.get("rate", "0%"))
            pitch = _percent(attrs.get("pitch", "0%"))
    text = html.unescape(_TAG.sub("", ssml))
    return voice, " ".join(text.split()), rate, pitch


def words(text: str) -> list[tuple[str, bool]]:
    """(text, is_word) in order, split as Azure reports boundaries: whitespace separates words, punctuation around a
    word is its own entry, apostrophes and hyphens inside a word stay in it."""
    out: list[tuple[str, bool]] = []
    for chunk in text.split():
        i, j = 0, len(chunk)
        while i < j and not chunk[i].isalnum():
            out.append((chunk[i], False))
            i += 1
        quoted = i > 0 and chunk[i - 1] in "'’"  # a closing quote, not an elision (po', un')
        trail = []
        while j > i and not chunk[j - 1].isalnum() and (quoted or chunk[j - 1] not in "'’" or j - 1 == i):
            trail.append((chunk[j - 1], False))
            j -= 1
        if i < j:
            out.append((chunk[i:j], True))
        out.extend(reversed(trail))
    return out


def _period(voice: str, word: str, pitch: int) -> int:
    base = 45 + int(hashlib.sha256(voice.encode()).hexdigest()[:4], 16) % 40  # 300–530 Hz per voice
    wobble = int(hashlib.sha256(word.lower().encode()).hexdigest()[:2], 16) % 9 - 4
    return max(20, (base + wobble) * 100 // (100 + pitch))


def _burst(samples: int, period: int) -> array.array:
    ramp = audio_pcm.ms_to_samples(RAMP_MS)
    out = array.array("h")
    half = period // 2
    for i in range(samples):
        phase = i % period
        tri = (
            (4 * AMPLITUDE * phase) // period - AMPLITUDE
            if phase < half
            else 3 * AMPLITUDE - (4 * AMPLITUDE * phase) // period
        )
        env = min(i, samples - 1 - i, ramp)
        out.append(tri * env // ramp)
    return out


def render(ssml: str) -> SynthesisResult:
    voice, text, rate, pitch = parse_ssml(ssml)
    pcm = array.array("h", bytes(2 * audio_pcm.ms_to_samples(LEAD_MS)))
    bounds: list[WordBoundary] = []

    def now_ms() -> int:
        return audio_pcm.samples_to_ms(len(pcm))

    for piece, is_word in words(text):
        if not is_word:
            bounds.append(WordBoundary(piece, now_ms(), 0))
            pause = COMMA_PAUSE_MS if piece in ",;:" else STOP_PAUSE_MS if piece in ".?!…" else 0
            pcm.frombytes(bytes(2 * audio_pcm.ms_to_samples(pause)))
            continue
        letters = sum(1 for ch in piece if ch.isalnum())
        dur = (70 + 45 * letters) * 100 // (100 + rate)
        start = now_ms()
        pcm.extend(_burst(audio_pcm.ms_to_samples(dur), _period(voice, piece, pitch)))
        bounds.append(WordBoundary(piece, start, now_ms() - start))
        pcm.frombytes(bytes(2 * audio_pcm.ms_to_samples(WORD_GAP_MS)))
    pcm.frombytes(bytes(2 * audio_pcm.ms_to_samples(TAIL_MS)))
    return SynthesisResult(audio_pcm.wav_bytes(audio_pcm.Pcm(pcm.tobytes())), bounds)


class MockProvider:
    """Same interface as `AzureBatchClient.synthesize`."""

    name = "mock"

    def synthesize(self, job_id: str, ssml_inputs: list[str]) -> list[SynthesisResult]:
        return [render(s) for s in ssml_inputs]
