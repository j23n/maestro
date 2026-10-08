"""`content tts [--unit uNN] [--only ID…] [--dry-run] [--provider azure|mock] [--cache DIR] [--show TARGET]`
(docs/04 § Audio).

1. **Collect** the needs: the pack compiler walks the dev scope (drafts included) and describes every voiced thing
   (`tts_needs`); `--unit` and `--only` (a text, item or exercise ID) narrow them.
2. **Render** each utterance not in the cache yet, in batch jobs of at most 1,000 inputs: Azure (`AZURE_SPEECH_KEY`,
   `AZURE_SPEECH_ENDPOINT` from the environment) or the offline mock. Renders go into the render cache as FLAC with
   their word boundaries (`tts_cache`): Azure's into `content-build/tts-cache/` (Git LFS), the mock's into
   `build/tts-mock-cache/` (never committed). `--dry-run` stops before rendering and prints the characters and cost.
3. **Align** every text line's word boundaries to its tokens, **assemble** each text in PCM and **encode** each file
   once into `build/audio/` (`audio_assets`), so `content build` finds them.

It fails (exit 1) on Azure errors, alignment failures and needs that can't be voiced (a speaker without a voice, a
display form TTS can't read, a model answer with a personal slot); renders already made stay in the cache.
`--show` prints the SSML (with any `<phoneme>` overrides) and the cache state of a text line, text, item or exercise:
the IPA override workflow in docs/04 § Audio › Pronunciation.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from itcontent import audio_pcm, paths
from itcontent.audio_assets import AudioPlan, AudioResolver, Missing, Resolved
from itcontent.course import load_course
from itcontent.pack.build import ENCODE_CACHE, MOCK_CACHE, TTS_CACHE, select_scope
from itcontent.pack.common import BuildError, Report
from itcontent.pack.compile import Compiler
from itcontent.pack.locks import Locks
from itcontent.tts_azure import MAX_INPUTS_PER_JOB, AzureError, SynthesisResult, cost_usd
from itcontent.tts_cache import RenderCache
from itcontent.tts_needs import Need, Speech, ipa_problem

PROVIDERS = ("azure", "mock")


class Provider(Protocol):
    def synthesize(self, job_id: str, ssml_inputs: list[str]) -> list[SynthesisResult]: ...


def collect(root: Path) -> tuple[Any, AudioPlan]:
    """Every need of the dev scope, as the pack build sees them."""
    course = load_course(root)
    for rel, msg in course.load_errors:
        raise BuildError(f"{rel}: {msg}")
    report = Report()
    scope = select_scope(course, "dev", allow_partial=False, report=report)
    plan = AudioPlan()
    Compiler(course, Locks(root), scope, report, plan).compile()
    return course, plan


def select(plan: AudioPlan, unit: str | None, only: Sequence[str]) -> list[Need]:
    needs = list(plan.needs.values())
    if unit:
        needs = [n for n in needs if n.unit == unit]
    if only:
        needs = [n for n in needs if n.matches(only)]
    return needs


def default_cache(root: Path, provider: str) -> RenderCache:
    return RenderCache(root / (MOCK_CACHE if provider == "mock" else TTS_CACHE), provider)


def make_provider(provider: str) -> Provider:
    if provider == "mock":
        from itcontent.tts_mock import MockProvider

        return MockProvider()
    import requests

    from itcontent.tts_azure import AzureBatchClient

    return AzureBatchClient(requests.Session())


def job_id(keys: Sequence[str]) -> str:
    digest = hashlib.sha256("\n".join(keys).encode()).hexdigest()[:12]
    return f"italiano-{digest}-{uuid.uuid4().hex[:8]}"


def show(needs: list[Need], target: str, caches: list[RenderCache], echo: Callable[[str], Any]) -> int:
    """The SSML and cache state of every line matching `target` (a line `<textId>#n`, or a text, item or exercise)."""
    shown = 0
    for need in needs:
        for line in need.lines:
            if target not in (need.owner, need.key, line.label):
                continue
            cached = next((c.name for c in caches if c.has(line.speech.key)), None)
            echo(f"{line.label} · {need.key} · {line.speech.voice.name}")
            for word, ipa in line.speech.overrides:
                echo(f"  override: {word} → /{ipa}/")
            echo(f"  ssml: {line.speech.ssml}")
            echo(f"  key: {line.speech.key} ({'cached: ' + cached if cached else 'not rendered'})")
            shown += 1
        if need.problem and target in (need.owner, need.key):
            echo(f"{need.key}: can't be voiced: {need.problem}")
            shown += 1
    if not shown:
        echo(f"error: no voiced line, text, item or exercise {target}")
        return 1
    return 0


def run_tts(
    root: Path | None = None,
    *,
    unit: str | None = None,
    only: Sequence[str] = (),
    dry_run: bool = False,
    provider: str = "azure",
    cache: Path | None = None,
    show_target: str | None = None,
    echo: Callable[[str], Any] = print,
    client: Provider | None = None,
    batch_size: int = MAX_INPUTS_PER_JOB,
    lint: bool = True,
) -> int:
    root = (root or paths.ROOT).resolve()
    if provider not in PROVIDERS:
        echo(f"error: --provider is one of {', '.join(PROVIDERS)}")
        return 2
    if lint:
        from itcontent.lint import lint_findings

        errors = [f for f in lint_findings(root) if f.level == "error"]
        if errors:
            for f in errors:
                echo(str(f))
            echo(f"error: content lint: {len(errors)} error(s); fix them first")
            return 1
    try:
        course, plan = collect(root)
    except BuildError as exc:
        echo(f"error: {exc}")
        return 1
    if unit and unit not in {u.id for u in course.units}:
        echo(f"error: unknown unit {unit}")
        return 2
    needs = select(plan, unit, only)
    target = RenderCache(cache, provider) if cache else default_cache(root, provider)
    lookup = [target] if cache or provider == "azure" else [default_cache(root, "azure"), target]
    if show_target:
        return show(needs, show_target, lookup, echo)

    status = 0
    kinds: dict[str, int] = {}
    for n in needs:
        kinds[n.kind] = kinds.get(n.kind, 0) + 1
    voiceable = [n for n in needs if n.problem is None]
    echo(
        f"needs: {len(needs)} ({', '.join(f'{v} {k}' for k, v in sorted(kinds.items())) or 'none'}); "
        f"{len(needs) - len(voiceable)} can't be voiced"
    )
    for n in needs:
        if n.problem is not None:
            echo(f"error: {n.key}: {n.problem}")
            status = 1
        for note in n.notes:
            echo(f"warning: {note}")
    speeches: dict[str, Speech] = {}
    for n in voiceable:
        for line in n.lines:
            speeches.setdefault(line.speech.key, line.speech)
    todo = [s for k, s in sorted(speeches.items()) if not any(c.has(k) for c in lookup)]
    chars = sum(s.characters for s in todo)
    echo(
        f"utterances: {len(speeches)}; {len(speeches) - len(todo)} cached, {len(todo)} to render "
        f"({chars:,} characters, ${cost_usd(chars):.2f} at $15 per 1M)"
    )
    for s in speeches.values():
        for word, ipa in s.overrides:
            problem = ipa_problem(ipa)
            if problem:
                echo(f"warning: <phoneme> for {word!r}: {problem}")
    if dry_run:
        return status
    if todo and provider != "mock" and not audio_pcm.have_ffmpeg():
        echo("error: ffmpeg is needed to store renders as FLAC (docs/02 § Dependencies)")
        return 1

    if todo:
        try:
            synth = client or make_provider(provider)
        except AzureError as exc:
            echo(f"error: {exc}")
            return 1
        jobs = 0
        for start in range(0, len(todo), batch_size):
            batch = todo[start : start + batch_size]
            try:
                results = synth.synthesize(job_id([s.key for s in batch]), [s.ssml for s in batch])
            except AzureError as exc:
                echo(f"error: {exc} ({start} of {len(todo)} rendered before it; they stay cached)")
                return 1
            if len(results) != len(batch):
                echo(f"error: the provider answered {len(results)} results for {len(batch)} inputs")
                return 1
            for s, res in zip(batch, results, strict=True):
                try:
                    pcm = audio_pcm.read_wav_bytes(res.wav, f"render of {s.text!r}")
                except ValueError as exc:
                    echo(f"error: {exc}")
                    return 1
                target.put(s.key, pcm, res.boundaries, voice=s.voice, ssml=s.ssml, text=s.text, provider=provider)
            jobs += 1
        echo(f"rendered {len(todo)} utterance(s) with {provider} in {jobs} job(s) into {_rel(target.root, root)}")

    resolver = AudioResolver(lookup, root / ENCODE_CACHE)
    resolved: list[Resolved] = []
    aligned = 0
    for n in voiceable:
        r = resolver.resolve(n)
        if isinstance(r, Missing):
            echo(f"error: {r.detail}")
            status = 1
            continue
        resolved.append(r)
        aligned += sum(1 for ln in n.lines if ln.align is not None)
    if aligned:
        echo(f"aligned {aligned} text line(s)")
    fresh = {r.audio_id for r in resolved if not (root / ENCODE_CACHE / r.file).is_file()}
    files, problems = resolver.encode(resolved)
    for p in problems:
        echo(f"error: {p}")
        status = 1
    size = sum(p.stat().st_size for p in files.values())
    echo(
        f"encoded {len(fresh) - len(problems)} new file(s); {len(files)} file(s) for these needs "
        f"({size / 2**20:.2f} MB) in {_rel(root / ENCODE_CACHE, root)}"
    )
    return status


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)
