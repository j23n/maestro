"""Voices, SSML, cache keys and the Azure AI Speech batch synthesis client (docs/04 § Audio, ADR-07).

Secrets come from the environment (`AZURE_SPEECH_KEY`, `AZURE_SPEECH_ENDPOINT`) and are never written anywhere.
Tests never touch the network: the client takes a `requests.Session`-like object, and tests pass recorded responses.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import time
import unicodedata
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from xml.sax.saxutils import escape, quoteattr

API_VERSION = "2024-04-01"
OUTPUT_FORMAT = "riff-24khz-16bit-mono-pcm"
MAX_INPUTS_PER_JOB = 1000
COST_PER_MILLION_CHARS_USD = 15.0


def fnv1a64(text: str) -> int:
    h = 0xCBF29CE484222325
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


@dataclass(frozen=True)
class Voice:
    name: str
    rate: str = "0%"
    pitch: str = "0%"
    style: str = ""
    effect: str = ""  # "station" for announcements

    @property
    def station(self) -> bool:
        return self.effect == "station"


class VoiceBook:
    """`content/voices.yaml`: one voice per speaker, `items` for words and chunks, `ch:extra` by FNV-1a 64 of the
    text ID, and `ch:you` with an m and an f voice (lines with {m:…|f:…} forms are rendered twice)."""

    def __init__(self, doc: dict[str, Any]) -> None:
        self.default_rate = str(doc.get("default_rate") or "0%")
        self.voices: dict[str, Any] = dict(doc.get("voices") or {})

    def _make(self, spec: dict[str, Any]) -> Voice:
        return Voice(
            name=str(spec["voice"]),
            rate=str(spec.get("rate") or self.default_rate),
            pitch=str(spec.get("pitch") or "0%"),
            style=str(spec.get("style") or ""),
            effect=str(spec.get("effect") or ""),
        )

    def for_speaker(self, speaker: str, *, text_id: str = "", gender: str = "m") -> Voice:
        key = {"ch:narrator": "narrator", "ch:announcer": "announcer"}.get(speaker, speaker)
        spec = self.voices.get(key)
        if spec is None:
            raise KeyError(f"voices.yaml has no voice for {speaker}")
        if key == "ch:extra":
            names = list(spec["voices"])
            return Voice(name=str(names[fnv1a64(text_id) % len(names)]), rate=self.default_rate)
        if key == "ch:you":
            return self._make(spec["f" if gender == "f" else "m"])
        return self._make(spec)

    def for_items(self) -> Voice:
        return self._make(self.voices["items"])


def ssml(text_parts: list[tuple[str, str | None]], voice: Voice, lang: str = "it-IT") -> str:
    """Build SSML. `text_parts` is the text split into (fragment, ipa-or-None) so pronunciation overrides become
    `<phoneme alphabet="ipa" ph="…">word</phoneme>`."""
    body = "".join(
        escape(frag) if ipa is None else f'<phoneme alphabet="ipa" ph={quoteattr(ipa)}>{escape(frag)}</phoneme>'
        for frag, ipa in text_parts
    )
    prosody_attrs = f" rate={quoteattr(voice.rate)}"
    if voice.pitch and voice.pitch != "0%":
        prosody_attrs += f" pitch={quoteattr(voice.pitch)}"
    inner = f"<prosody{prosody_attrs}>{body}</prosody>"
    if voice.style:
        inner = f"<mstts:express-as style={quoteattr(voice.style)}>{inner}</mstts:express-as>"
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{lang}">'
        f"<voice name={quoteattr(voice.name)}>{inner}</voice></speak>"
    )


def apply_overrides(text: str, lexicon: dict[str, str]) -> list[tuple[str, str | None]]:
    """Split `text` so each whole word found in `lexicon` (case-insensitive) carries its IPA.

    Apostrophes belong to words (`quant'è`, `po'`), except quotes around a word. An elided form keeps its apostrophe
    with the word before it (`l'ancora`): when the whole form isn't in the lexicon, the part after its last apostrophe
    is looked up, and only that part gets the `<phoneme>`."""
    if not lexicon:
        return [(text, None)]
    lower = {k.lower(): v for k, v in lexicon.items()}
    out: list[tuple[str, str | None]] = []
    buf = ""
    word = ""

    def match(w: str) -> tuple[str, str, str] | None:
        """(text before the override, the overridden part, text after) or None."""
        core = w.lstrip("'’")
        lead = w[: len(w) - len(core)]
        for cand in (core, core.rstrip("'’")):
            if cand and cand.lower() in lower:
                return lead, cand, core[len(cand) :]
        inner = core.rstrip("'’")
        cut = max(inner.rfind("'"), inner.rfind("’")) + 1
        if 0 < cut < len(inner) and inner[cut:].lower() in lower:
            return lead + inner[:cut], inner[cut:], core[len(inner) :]
        return None

    def flush_word() -> None:
        nonlocal word, buf
        if not word:
            return
        found = match(word)
        if found is None:
            buf += word
        else:
            before, part, after = found
            buf += before
            if buf:
                out.append((buf, None))
            out.append((part, lower[part.lower()]))
            buf = after
        word = ""

    for ch in text:
        if ch.isalpha() or ch in "'’":
            word += ch
        else:
            flush_word()
            buf += ch
    flush_word()
    if buf:
        out.append((buf, None))
    return out


def billable_characters(parts: list[tuple[str, str | None]]) -> int:
    """An estimate of what Azure bills for one input: the spoken text plus the IPA of `<phoneme>` overrides (SSML
    markup itself is not billed)."""
    return sum(len(frag) + (len(ipa) if ipa else 0) for frag, ipa in parts)


def cache_key(voice: Voice, ssml_text: str, output_format: str = OUTPUT_FORMAT) -> str:
    """sha256 of voice, style, rate, pitch, SSML and output format (docs/04 § Audio step 3)."""
    payload = json.dumps(
        {
            "voice": voice.name,
            "style": voice.style,
            "rate": voice.rate,
            "pitch": voice.pitch,
            "ssml": ssml_text,
            "format": output_format,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cost_usd(characters: int) -> float:
    return characters * COST_PER_MILLION_CHARS_USD / 1_000_000


@dataclass(frozen=True)
class WordBoundary:
    text: str
    offset_ms: int
    duration_ms: int


@dataclass
class SynthesisResult:
    wav: bytes
    boundaries: list[WordBoundary] = field(default_factory=list)


class AzureError(RuntimeError):
    pass


def _error_text(r: Any) -> str:
    """The message of an Azure error response (`{"code", "message"}` or `{"error": {"code", "message"}}`)."""
    try:
        body = r.json()
    except Exception:
        return str(getattr(r, "text", ""))[:300]
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        parts = [str(err.get(k)) for k in ("code", "message") if err.get(k)]
        if parts:
            return ": ".join(parts)
    return json.dumps(body)[:300]


class AzureBatchClient:
    """Azure AI Speech batch synthesis (REST, `api-version=2024-04-01`; docs/04 § Audio step 4).

    `synthesize` creates a job (`PUT …/batchsyntheses/{id}`), polls it until it succeeds or fails, downloads the result
    ZIP from `outputs.result` (a SAS URL: no key is sent there), checks `summary.json` for inputs that failed, and
    deletes the job. Throttling (429) and server errors (5xx) are retried after `Retry-After` (or `poll_seconds`), up
    to `retries` times in a row.
    """

    def __init__(
        self,
        session: Any,
        endpoint: str | None = None,
        key: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        poll_seconds: float = 5.0,
        timeout_s: float = 3600,
        retries: int = 5,
    ) -> None:
        self.session = session
        self.endpoint = (endpoint or os.environ.get("AZURE_SPEECH_ENDPOINT") or "").rstrip("/")
        self.key = key or os.environ.get("AZURE_SPEECH_KEY") or ""
        if not self.endpoint or not self.key:
            raise AzureError("set AZURE_SPEECH_KEY and AZURE_SPEECH_ENDPOINT (never commit them)")
        self.sleep = sleep
        self.poll_seconds = poll_seconds
        self.timeout_s = timeout_s
        self.retries = retries

    def _url(self, job_id: str) -> str:
        return f"{self.endpoint}/texttospeech/batchsyntheses/{job_id}?api-version={API_VERSION}"

    def _headers(self) -> dict[str, str]:
        return {"Ocp-Apim-Subscription-Key": self.key, "Content-Type": "application/json"}

    def _send(self, what: str, call: Callable[[], Any], ok: tuple[int, ...]) -> Any:
        for attempt in range(self.retries + 1):
            r = call()
            if r.status_code in ok:
                return r
            if (r.status_code == 429 or r.status_code >= 500) and attempt < self.retries:
                headers = getattr(r, "headers", None) or {}
                try:
                    wait = float(headers.get("Retry-After", self.poll_seconds))
                except ValueError:
                    wait = self.poll_seconds
                self.sleep(wait)
                continue
            raise AzureError(f"{what}: HTTP {r.status_code} {_error_text(r)}")
        raise AzureError(f"{what}: gave up after {self.retries} retries")  # pragma: no cover

    def synthesize(self, job_id: str, ssml_inputs: list[str]) -> list[SynthesisResult]:
        if not ssml_inputs:
            return []
        if len(ssml_inputs) > MAX_INPUTS_PER_JOB:
            raise AzureError(f"at most {MAX_INPUTS_PER_JOB} inputs per job (got {len(ssml_inputs)})")
        body = {
            "description": "Italiano course audio",
            "inputKind": "SSML",
            "inputs": [{"content": s} for s in ssml_inputs],
            "properties": {
                "outputFormat": OUTPUT_FORMAT,
                "wordBoundaryEnabled": True,
                "sentenceBoundaryEnabled": True,
                "concatenateResult": False,
                "decompressOutputFiles": False,
            },
        }
        url = self._url(job_id)
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self._send(
            f"create job {job_id}", lambda: self.session.put(url, headers=self._headers(), data=data), (200, 201)
        )
        waited = 0.0
        while True:
            r = self._send(f"poll job {job_id}", lambda: self.session.get(url, headers=self._headers()), (200,))
            job = r.json()
            status = job.get("status")
            if status == "Succeeded":
                break
            if status == "Failed":
                props = job.get("properties") or {}
                detail = props.get("error") or props
                raise AzureError(f"job {job_id} failed: {json.dumps(detail, ensure_ascii=False)[:500]}")
            if waited >= self.timeout_s:
                raise AzureError(f"job {job_id} timed out after {waited:.0f} s (status {status})")
            self.sleep(self.poll_seconds)
            waited += self.poll_seconds
        result_url = (job.get("outputs") or {}).get("result")
        if not result_url:
            raise AzureError(f"job {job_id} succeeded without outputs.result")
        z = self._send(f"download {job_id}", lambda: self.session.get(result_url), (200,))
        results = parse_result_zip(z.content, len(ssml_inputs), ssml_inputs)
        with contextlib.suppress(Exception):  # the results are in hand; a job left behind expires anyway
            self.session.delete(url, headers=self._headers())
        return results


def parse_result_zip(data: bytes, expected: int, inputs: list[str] | None = None) -> list[SynthesisResult]:
    """`NNNN.wav` with its `NNNN.word.json` per input, in input order. `summary.json` (when present) names the file
    of each input and its status; any input that didn't succeed is an error naming it."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        files = [f"{i:04d}.wav" for i in range(1, expected + 1)]
        if "summary.json" in names:
            summary = json.loads(zf.read("summary.json").decode("utf-8-sig") or "{}")
            results = summary.get("results") if isinstance(summary, dict) else None
            if isinstance(results, list) and results:
                if len(results) != expected:
                    raise AzureError(f"result ZIP: summary.json lists {len(results)} results for {expected} inputs")
                failed = []
                for i, res in enumerate(results):
                    if res.get("status") != "Succeeded":
                        props = res.get("properties") or {}
                        why = props.get("errorMessage") or props.get("error") or res.get("status")
                        shown = (inputs[i] if inputs else "")[:120]
                        failed.append(f"input {i + 1} ({shown}): {why}")
                    elif res.get("audioFileName"):
                        files[i] = str(res["audioFileName"])
                if failed:
                    raise AzureError("inputs failed: " + "; ".join(failed))
        out = []
        for wav_name in files:
            if wav_name not in names:
                raise AzureError(f"result ZIP lacks {wav_name}")
            bounds: list[WordBoundary] = []
            wj = wav_name.rsplit(".", 1)[0] + ".word.json"
            if wj in names:
                for b in json.loads(zf.read(wj).decode("utf-8-sig")):
                    bounds.append(WordBoundary(str(b["Text"]), int(b["AudioOffset"]), int(b["Duration"])))
            out.append(SynthesisResult(zf.read(wav_name), bounds))
        return out


class AlignmentError(ValueError):
    pass


def _norm_word(text: str) -> str:
    """Lowercase NFC letters, digits and apostrophes; an opening quote is not part of a word."""
    t = unicodedata.normalize("NFC", text).lower().replace("’", "'").replace("‘", "'")
    return "".join(ch for ch in t if ch.isalnum() or ch == "'").lstrip("'")


def _same(a: str, b: str) -> bool:
    """Equal, or equal but for a final apostrophe (an elision on one side, a closing quote on the other)."""
    return a == b or a.rstrip("'") == b.rstrip("'")


def align(tokens: list[str], bounds: list[WordBoundary], label: str) -> list[tuple[int, int]]:
    """Map Azure word boundaries onto our word tokens, in order (docs/04 § Audio step 5).

    Punctuation entries are skipped. One boundary may cover several of our tokens (`quant'è` → `quant'` + `è`)
    and one token may span several boundaries (`e-mail`); times are split by character share. Any other mismatch
    is an error that names the line. Returns (start_ms, end_ms) per token, relative to the line's audio.
    """
    words = [(b, _norm_word(b.text)) for b in bounds]
    words = [(b, w) for b, w in words if w.strip("'")]
    toks = [_norm_word(t) for t in tokens]
    out: list[tuple[int, int]] = []
    ti = 0
    wi = 0
    while ti < len(toks):
        if not toks[ti].strip("'"):
            raise AlignmentError(f"{label}: token {ti} '{tokens[ti]}' has no letters to align")
        if wi >= len(words):
            raise AlignmentError(f"{label}: audio ends before token {ti} '{tokens[ti]}'")
        b, w = words[wi]
        if _same(w, toks[ti]):
            out.append((b.offset_ms, b.offset_ms + b.duration_ms))
            ti += 1
            wi += 1
            continue
        if w.startswith(toks[ti]):  # one boundary covers several tokens
            group = []
            acc = ""
            while ti < len(toks) and len(acc) < len(w) and w.startswith(acc + toks[ti]):
                acc += toks[ti]
                group.append(ti)
                ti += 1
            if not _same(acc, w):
                raise AlignmentError(f"{label}: heard '{b.text}' but the text has '{''.join(tokens[group[0] : ti])}…'")
            total = sum(len(toks[g]) for g in group)
            start = b.offset_ms
            for g in group:
                share = round(b.duration_ms * len(toks[g]) / total)
                out.append((start, start + share))
                start += share
            out[-1] = (out[-1][0], b.offset_ms + b.duration_ms)
            wi += 1
            continue
        if toks[ti].startswith(w):  # one token spans several boundaries
            acc = ""
            first = b
            last = b
            while wi < len(words) and len(acc) < len(toks[ti]) and toks[ti].startswith(acc + words[wi][1]):
                last = words[wi][0]
                acc += words[wi][1]
                wi += 1
            if not _same(acc, toks[ti]):
                raise AlignmentError(f"{label}: token '{tokens[ti]}' does not match the audio words around '{b.text}'")
            out.append((first.offset_ms, last.offset_ms + last.duration_ms))
            ti += 1
            continue
        raise AlignmentError(f"{label}: expected '{tokens[ti]}' (token {ti}) but the audio says '{b.text}'")
    return out
