"""Audio for the review pages (docs/04 § Content review loop › Review pages, check 9): what the audio reviewer hears.

The page embeds each audio file of its scope once (`data:` URIs built by the page script from base64, so the page stays
one self-contained file) and puts a play button on every element that has audio: a text (the whole file), each line
(its segment of the text's file), an item, a sound item's pair words, an exercise's voiced string (dictation, repeat,
a voiced prompt, a model answer with `audio_after`, a talk model, sound-pair words) and each conversation line. The
audio is what `content build` would bundle: the same needs, renders (Azure first, then mock) and encoded files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from itcontent import audio_pcm
from itcontent.audio_assets import AudioPlan, AudioResolver, Resolved
from itcontent.course import Course
from itcontent.pack.build import AudioOptions, select_scope
from itcontent.pack.common import BuildError, Report
from itcontent.pack.compile import Compiler
from itcontent.pack.locks import Locks
from itcontent.review import scope_files

MAIN_SLOTS = ("audioId", "answerAudioId", "promptAudioId", "modelAudioId")


@dataclass(frozen=True)
class AudioRef:
    """Where an element's audio is: a file, and for a line the segment of its text's file."""

    audio_id: str
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass
class ReviewAudio:
    refs: dict[str, AudioRef] = field(default_factory=dict)  # element target (or sub-target) → audio
    files: dict[str, bytes] = field(default_factory=dict)  # audio ID → .m4a bytes
    note: str = ""  # why there is no audio, when that's not simply "nothing rendered yet"

    def ref(self, target: str) -> AudioRef | None:
        return self.refs.get(target)


def targets(r: Resolved) -> dict[str, AudioRef]:
    """The page targets a resolved need plays for."""
    need = r.need
    whole = AudioRef(r.audio_id)
    if need.kind == "text":
        out = {need.owner: whole}
        for line, timed in zip(need.lines, r.lines, strict=True):
            out[line.label] = AudioRef(r.audio_id, timed.start_ms, timed.end_ms)
        return out
    if need.kind == "item":
        return {need.owner: whole}
    if need.kind == "sound":  # sound:<item>:<pair>:<word>
        pair, word = need.key.rsplit(":", 2)[1:]
        return {f"{need.owner}:{pair}:{word}": whole}
    slot = need.key.split(":", 1)[1][len(need.owner) + 1 :]  # exercise:<id>:<slot>
    if slot in MAIN_SLOTS:
        return {need.owner: whole}
    if slot.startswith("nodes."):
        return {f"{need.owner}/{slot[6:]}": whole}
    return {f"{need.owner}:{slot}": whole}


def page_audio(root: Path, course: Course, scope: str, options: AudioOptions | None = None) -> ReviewAudio:
    """The audio of a review page's scope (none for the sign-off files)."""
    if scope == "specs":
        return ReviewAudio()
    options = options or AudioOptions.default(root, "dev")
    if not any(c.keys() for c in options.caches):
        return ReviewAudio()  # nothing rendered yet
    resolver = AudioResolver(options.caches, options.encode_dir)
    plan = AudioPlan(resolver)
    try:
        report = Report()
        scope_ = select_scope(course, "dev", allow_partial=False, report=report)
        Compiler(course, Locks(root), scope_, report, plan).compile()
    except Exception as exc:  # the page shows the content without audio; the build reports the problem
        detail = str(exc) if isinstance(exc, BuildError) else f"{type(exc).__name__}: {exc}"
        return ReviewAudio(note=f"no audio: the pack doesn't compile ({detail})")
    files_on_page = set(scope_files(course, scope))
    resolved = [
        r for n in plan.needs.values() if n.part in files_on_page and isinstance(r := resolver.resolve(n), Resolved)
    ]
    if not resolved:
        return ReviewAudio()
    if not audio_pcm.have_ffmpeg() and not all(
        (p := resolver.encoded_path(r)) is not None and p.is_file() for r in resolved
    ):
        return ReviewAudio(note="no audio: ffmpeg is needed to encode it (docs/02 § Dependencies)")
    paths, problems = resolver.encode(resolved)
    out = ReviewAudio(note=f"{len(problems)} audio file(s) couldn't be encoded: {problems[0]}" if problems else "")
    for r in sorted(resolved, key=lambda r: r.need.key):
        path = paths.get(r.file)
        if path is None:
            continue
        out.files.setdefault(r.audio_id, path.read_bytes())
        for target, ref in targets(r).items():
            out.refs.setdefault(target, ref)
    return out
