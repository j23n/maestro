"""`content tts` end to end (M5.1, M5.4; docs/04 § Audio): collect the needs, render (the offline mock, or Azure through
recorded responses), cache, align, assemble, encode once; then the pack build, the review pages and the report use the
renders. Every test works on a throwaway copy of the frozen seed course (conftest); nothing touches the network.
"""

from __future__ import annotations

import io
import itertools
import json
import re
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import copy_course, copy_seed
from itcontent.audio_pcm import read_wav_bytes
from itcontent.cli import app
from itcontent.pack import build as build_mod
from itcontent.pack.build import AudioOptions, BuildError, build_pack, select_scope
from itcontent.review_export import export
from itcontent.tts import run_tts
from itcontent.tts_azure import AzureBatchClient, SynthesisResult, WordBoundary
from itcontent.tts_cache import RenderCache
from itcontent.tts_mock import MockProvider, render

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
STORY_LINES = 22


def tts(repo: Path, **kw) -> tuple[int, list[str]]:
    out: list[str] = []
    code = run_tts(repo, echo=out.append, lint=False, **kw)
    return code, out


def line(out: list[str], prefix: str) -> str:
    return next(x for x in out if x.startswith(prefix))


@pytest.fixture(scope="module")
def rendered(tmp_path_factory) -> Path:
    """A course copy whose Unit 2 is rendered with the mock provider."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    repo = copy_seed(tmp_path_factory.mktemp("tts") / "repo")
    code, out = tts(repo, provider="mock", unit="u02")
    assert code == 0, out
    return repo


@pytest.fixture(scope="module")
def dev_pack(rendered) -> tuple[build_mod.BuildResult, sqlite3.Connection]:
    result = build_pack(rendered, mode="dev", out=rendered / "bundle" / "content.sqlite", lint=False, echo=print)
    con = sqlite3.connect(f"file:{result.path}?mode=ro", uri=True)
    yield result, con
    con.close()


# ---------------------------------------------------------------- the command


def test_dry_run_prints_characters_and_cost_and_renders_nothing(course_copy):
    code, out = tts(course_copy, provider="mock", unit="u02", dry_run=True)
    assert code == 0, out
    assert line(out, "needs:").startswith("needs: 60 (29 exercise, 29 item, 2 text)")
    m = re.match(r"utterances: (\d+); 0 cached, (\d+) to render \(([\d,]+) characters, \$(\d+\.\d\d) at \$15", out[1])
    assert m and m.group(1) == m.group(2), out
    chars = int(m.group(3).replace(",", ""))
    assert 1000 < chars < 2000 and m.group(4) == f"{chars * 15 / 1e6:.2f}"
    assert not (course_copy / "build").exists()


def test_mock_tts_renders_caches_aligns_and_encodes_once(rendered):
    cache = RenderCache(rendered / "build" / "tts-mock-cache", "mock")
    keys = cache.keys()
    assert len(keys) > 60
    meta = cache.meta(keys[0])
    assert meta is not None and meta.provider == "mock" and meta.boundaries
    assert cache.pcm(keys[0]).samples == meta.samples  # stored as WAV, checked against its hash
    assert (rendered / "build" / "tts-mock-cache" / keys[0][:2] / f"{keys[0]}.wav").is_file()
    assert not (rendered / "content-build").exists()  # mock renders never go to the Azure cache
    encoded = sorted((rendered / "build" / "audio").glob("*.m4a"))
    assert encoded and not list((rendered / "build" / "audio").glob("*.tmp"))
    stamps = {p: p.stat().st_mtime_ns for p in encoded}

    code, out = tts(rendered, provider="mock", unit="u02")  # everything is cached: nothing renders or re-encodes
    assert code == 0, out
    assert ", 0 to render" in line(out, "utterances:")
    assert line(out, "aligned") == f"aligned {STORY_LINES + 2} text line(s)"
    assert line(out, "encoded").startswith("encoded 0 new file(s)")
    assert {p: p.stat().st_mtime_ns for p in encoded} == stamps


def test_only_and_unit_narrow_the_needs(rendered):
    code, out = tts(rendered, provider="mock", only=["u02.l1.story", "w:cornetto"], dry_run=True)
    assert code == 0 and line(out, "needs:").startswith("needs: 2 (1 item, 1 text)")
    code, out = tts(rendered, provider="mock", unit="u07", dry_run=True)
    assert code == 0 and line(out, "needs:").startswith("needs: 0 (none)")
    assert tts(rendered, provider="mock", unit="u42", dry_run=True)[0] == 2
    assert tts(rendered, provider="bogus")[0] == 2


def test_needs_that_cant_be_voiced_fail(course_copy):
    # A form TTS would read letter by letter (`sono nato/a`) needs `audio_say`; take the seed's away.
    items = course_copy / "content" / "items" / "u01.yaml"
    items.write_text(items.read_text().replace("audio_say: 'sono nato, sono nata', ", ""))
    code, out = tts(course_copy, provider="mock", only=["c:sono-nato"], dry_run=True)
    assert code == 1
    assert any("c:sono-nato" in x and "audio_say" in x for x in out), out


class Mangled:
    """Azure saying a word differently from the text (the reason voiced numbers are written in words)."""

    def synthesize(self, job_id: str, ssml_inputs: list[str]) -> list[SynthesisResult]:
        out = []
        for s in ssml_inputs:
            r = render(s)
            bounds = [
                WordBoundary("6" if b.text == "Sei" else b.text, b.offset_ms, b.duration_ms) for b in r.boundaries
            ]
            out.append(SynthesisResult(r.wav, bounds))
        return out


@needs_ffmpeg
def test_an_alignment_failure_names_the_line(course_copy):
    code, out = tts(course_copy, provider="mock", only=["u02.l1.story"], client=Mangled())
    assert code == 1
    assert any(x.startswith("error: u02.l1.story#20: expected 'Sei'") for x in out), out
    result = build_pack(course_copy, mode="dev", out=course_copy / "p" / "c.sqlite", lint=False, echo=lambda _: None)
    assert any(w.startswith("audio alignment: u02.l1.story#20") for w in result.report.warnings)


class RecordedAzure:
    """The Azure batch synthesis service as recorded (fixtures/azure): job resources as JSON, the result as a ZIP of
    `NNNN.wav` + `NNNN.word.json` + `summary.json`; the audio itself is synthetic."""

    def __init__(self) -> None:
        self.inputs: list[str] = []
        self.calls: list[str] = []

    class R:
        def __init__(self, status: int, body: object = None, content: bytes = b"") -> None:
            self.status_code, self._body, self.content, self.headers = status, body, content, {}
            self.text = json.dumps(body)

        def json(self) -> object:
            return self._body

    def put(self, url, headers=None, data=None):
        self.calls.append("PUT")
        self.inputs = [i["content"] for i in json.loads(data)["inputs"]]
        return self.R(201, {"id": "job", "status": "NotStarted"})

    def get(self, url, headers=None):
        self.calls.append("GET")
        if url.startswith("https://blob.example"):
            buf = io.BytesIO()
            results = []
            with zipfile.ZipFile(buf, "w") as zf:
                for i, s in enumerate(self.inputs, start=1):
                    r = render(s)
                    zf.writestr(f"{i:04d}.wav", r.wav)
                    words = [
                        {"Text": b.text, "AudioOffset": b.offset_ms, "Duration": b.duration_ms} for b in r.boundaries
                    ]
                    zf.writestr(f"{i:04d}.word.json", json.dumps(words))
                    results.append({"texts": [s], "status": "Succeeded", "audioFileName": f"{i:04d}.wav"})
                zf.writestr("summary.json", json.dumps({"status": "Succeeded", "results": results}))
            return self.R(200, content=buf.getvalue())
        return self.R(200, {"id": "job", "status": "Succeeded", "outputs": {"result": "https://blob.example/r.zip"}})

    def delete(self, url, headers=None):
        self.calls.append("DELETE")
        return self.R(204)


@needs_ffmpeg
def test_azure_renders_go_to_the_lfs_cache_as_flac(course_copy):
    service = RecordedAzure()
    client = AzureBatchClient(service, endpoint="https://x.example", key="k", sleep=lambda _: None)
    code, out = tts(course_copy, provider="azure", only=["u02.check.01.audio"], client=client)
    assert code == 0, out
    assert service.calls == ["PUT", "GET", "GET", "DELETE"]
    cache = RenderCache(course_copy / "content-build" / "tts-cache")
    keys = cache.keys()
    assert len(keys) == 2
    for k in keys:
        assert cache.audio_path(k).suffix == ".flac" and cache.meta(k).provider == "azure"
        assert cache.pcm(k) == read_wav_bytes(render(cache.meta(k).ssml).wav)  # lossless
    result = build_pack(course_copy, mode="dev", out=course_copy / "p" / "c.sqlite", lint=False, echo=lambda _: None)
    with sqlite3.connect(result.path) as con:
        voice = con.execute("SELECT a.voice FROM audio a JOIN texts t ON t.audio_id = a.id").fetchone()[0]
    assert voice.startswith("it-IT-") and "mock" not in voice


# ---------------------------------------------------------------- the pack build


def test_the_dev_pack_takes_audio_ids_rows_and_timings_from_the_renders(dev_pack, rendered):
    result, con = dev_pack
    assert any(w.startswith("mock audio:") for w in result.report.warnings)
    assert any(n.startswith("audio budget (MB now/projected): ") for n in result.report.notes)
    rows = con.execute("SELECT id, file, duration_ms, voice, sha256 FROM audio").fetchall()
    assert rows
    for aid, file, duration, voice, digest in rows:
        assert re.fullmatch(r"a:[0-9a-f]{12}", aid) and file == aid[2:] + ".m4a" and duration > 0
        assert voice.startswith("mock:") and len(digest) == 64 and digest.startswith(aid[2:])
    bundle = {p.name for p in (rendered / "bundle" / "Audio").glob("*.m4a")}
    assert bundle == {r[1] for r in rows}  # exactly the referenced files

    story = con.execute("SELECT audio_id, duration_ms FROM texts WHERE id = 'u02.l1.story'").fetchone()
    assert story[0] in {r[0] for r in rows} and story[1] == next(r[2] for r in rows if r[0] == story[0])
    spans = con.execute("SELECT ord, start_ms, end_ms FROM text_lines WHERE text_id = 'u02.l1.story' ORDER BY ord")
    spans = spans.fetchall()
    assert len(spans) == STORY_LINES and spans[0][1] == 0 and spans[-1][2] == story[1]
    assert all(a[2] < b[1] for a, b in itertools.pairwise(spans))  # gaps between lines
    untimed = con.execute(
        "SELECT COUNT(*) FROM tokens WHERE text_id LIKE 'u02.%' AND kind != 'punct' AND start_ms IS NULL"
    ).fetchone()[0]
    assert untimed == 0  # every word token of a voiced text has a timing
    assert con.execute("SELECT COUNT(*) FROM tokens WHERE kind = 'punct' AND start_ms IS NOT NULL").fetchone()[0] == 0
    for n, start, end in spans:
        timed = con.execute(
            "SELECT start_ms, end_ms FROM tokens WHERE text_id = 'u02.l1.story' AND line_ord = ? AND start_ms IS NOT "
            "NULL ORDER BY ord",
            (n,),
        ).fetchall()
        assert timed and timed[0][0] >= start and timed[-1][1] <= end
        assert [t[0] for t in timed] == sorted(t[0] for t in timed)

    def payload(eid: str) -> dict:
        return json.loads(con.execute("SELECT payload FROM exercises WHERE id = ?", (eid,)).fetchone()[0])

    ids = {r[0] for r in rows}
    assert payload("u02.l1.ex13")["audioId"] in ids  # dictation
    assert payload("u02.l1.ex14")["audioId"] in ids  # repeat
    assert payload("u02.l1.ex04")["answerAudioId"] in ids  # recall with audio_after
    assert payload("u02.l1.ex10")["answerAudioId"] is None  # sentence building without audio_after
    assert all(n["audioId"] in ids for n in payload("u02.l1.ex25")["nodes"])  # conversation lines
    assert all(w["audioId"] in ids for w in payload("u02.l1.ex22")["pair"])  # sound-pair words
    cornetto = con.execute("SELECT audio_id FROM items WHERE id = 'w:cornetto'").fetchone()[0]
    assert cornetto in ids
    match = payload("u02.l1.step-preview.b1.match")
    assert match["pairs"][2]["leftAudioId"] == cornetto  # the preview plays the item's own audio
    assert payload("u02.l1.step-preview.b2.c-cosa-prende")["promptAudioId"] in ids


def test_two_builds_with_audio_have_the_same_pack_hash(dev_pack, rendered):
    result, _ = dev_pack
    again = build_pack(rendered, mode="dev", out=rendered / "again" / "content.sqlite", lint=False, echo=print)
    assert again.content_hash == result.content_hash


def test_rows_dont_depend_on_encoding(dev_pack, rendered):
    """Without ffmpeg (or with encode=False) the rows are the same: they come from the renders' metadata."""
    result, _ = dev_pack
    options = AudioOptions.default(rendered, "dev")
    options.encode = False
    rows_only = build_pack(
        rendered, mode="dev", out=rendered / "rows" / "c.sqlite", lint=False, echo=print, audio=options
    )
    assert rows_only.content_hash == result.content_hash
    assert not (rendered / "rows" / "Audio").exists()


def test_a_release_never_uses_mock_audio(rendered, monkeypatch):
    def dev_scope_as_release(course, mode, *, allow_partial, report):
        scope = select_scope(course, "dev", allow_partial=allow_partial, report=report)
        scope.mode = "release"
        return scope

    monkeypatch.setattr(build_mod, "select_scope", dev_scope_as_release)
    with pytest.raises(BuildError, match=r"release: \d+ audio need\(s\) have no audio"):
        build_pack(rendered, mode="release", out=rendered / "release" / "c.sqlite", lint=False, echo=print)


def test_the_audio_budget_stops_the_build(rendered, monkeypatch):
    monkeypatch.setattr(build_mod, "AUDIO_BUDGET_BYTES", 10_000)
    with pytest.raises(BuildError, match="over the 0 MB budget"):
        build_pack(rendered, mode="dev", out=rendered / "over" / "c.sqlite", lint=False, echo=print)
    assert not (rendered / "over" / "c.sqlite").exists()


# ---------------------------------------------------------------- pronunciation (M5.4)


def test_an_ipa_override_is_shown_and_rerenders_only_its_lines(rendered, tmp_path):
    """The workflow of docs/04 § Pronunciation: a line `say:` fixes one line, a lexicon entry every line with the
    word; `--show` prints the SSML with its `<phoneme>`; only the lines concerned render again."""
    repo = copy_course(rendered, tmp_path / "repo")
    shutil.copytree(rendered / "build" / "tts-mock-cache", repo / "build" / "tts-mock-cache")
    lesson = repo / "content" / "units" / "02-al-bar" / "lesson-1.yaml"
    text = lesson.read_text(encoding="utf-8")
    old = 'it: "Ah, grazie! Un cornetto, per favore.", en: "Ah, thank you! A croissant, please."}'
    assert old in text
    lesson.write_text(text.replace(old, old[:-1] + ', say: {cornetto: "korˈnetto"}}'), encoding="utf-8")

    code, out = tts(repo, provider="mock", show_target="u02.l1.story#7")
    assert code == 0, out
    assert "  override: cornetto → /korˈnetto/" in out
    assert '<phoneme alphabet="ipa" ph="korˈnetto">cornetto</phoneme>' in line(out, "  ssml:")
    assert line(out, "  key:").endswith("(not rendered)")
    code, out = tts(repo, provider="mock", only=["u02.l1.story"], dry_run=True)
    assert ", 1 to render" in line(out, "utterances:")  # only line 7

    pron = repo / "content" / "pronunciation.yaml"
    pron.write_text(pron.read_text(encoding="utf-8") + '  grazie: "ˈɡrattsje"\n', encoding="utf-8")
    code, out = tts(repo, provider="mock", only=["u02.l1.story"], dry_run=True)
    assert ", 4 to render" in line(out, "utterances:")  # lines 7, 13, 16 and 21 say grazie
    code, out = tts(repo, provider="mock", only=["u02.l1.story"])
    assert code == 0, out

    from itcontent.report import build_report

    section = next(s for s in build_report(repo, unit="u02") if s.key == "pronunciation")
    rows = "\n".join(section.lines)
    voiced_in = "u02.check.07:nodes.end, u02.l1.ex25:nodes.end, u02.l1.ex25:nodes.n3, u02.l1.story#7, u02.l1.story#13"
    assert f"| grazie | /ˈɡrattsje/ | {voiced_in} (+4) | ok |" in rows  # story lines 16 and 21, and conversations
    assert "- u02.l1.story#7: *cornetto* → /korˈnetto/ (line `say`)" in rows


def test_a_say_key_that_isnt_in_the_line_is_reported(course_copy):
    lesson = course_copy / "content" / "units" / "02-al-bar" / "lesson-1.yaml"
    text = lesson.read_text(encoding="utf-8")
    old = 'it: "Mmm! Buono!", en: "Mmm! Delicious!"}'
    lesson.write_text(text.replace(old, old[:-1] + ', say: {buona: "ˈbwɔːna"}}'), encoding="utf-8")
    code, out = tts(course_copy, provider="mock", only=["u02.l1.story"], dry_run=True)
    assert code == 0
    assert "warning: u02.l1.story#18: `say` names 'buona', which isn't a word of the line" in out


# ---------------------------------------------------------------- review pages


def test_the_review_page_plays_the_rendered_audio(rendered, tmp_path):
    result = export("u02", root=rendered, out=tmp_path / "u02.html")
    page = result.path.read_text(encoding="utf-8")
    assert "audio file(s) embedded" in result.summary(rendered)
    audio = json.loads(re.search(r'<script type="application/json" id="review-audio">(.*?)</script>', page).group(1))
    assert audio and all(re.fullmatch(r"a:[0-9a-f]{12}", k) for k in audio)
    buttons = re.findall(r'<button type="button" class="play" data-audio="(a:[0-9a-f]{12})"([^>]*)>', page)
    assert {b[0] for b in buttons} <= set(audio)
    labels = re.findall(r'aria-label="([^"]+)"', page)
    assert "Play the text: u02.l1.story" in labels
    assert "Play line: u02.l1.story#3" in labels and "Play line: u02.l1.ex25/n1" in labels
    assert "Play: w:cornetto" in labels and "Play: u02.l1.ex13" in labels
    assert "Play the model answer: u02.l1.ex04" in labels and "Play: u02.l1.ex22:pair[1]" in labels
    line3 = next(attrs for aid, attrs in buttons if 'aria-label="Play line: u02.l1.story#3"' in attrs)
    assert re.search(r'data-start="\d+" data-end="\d+"', line3)  # a line plays its segment of the story's file


def test_no_renders_no_players(course_copy, tmp_path):
    result = export("u02", root=course_copy, out=tmp_path / "u02.html")
    page = result.path.read_text(encoding="utf-8")
    assert 'id="review-audio">{}</script>' in page and 'class="play"' not in page


# ---------------------------------------------------------------- the CLI


def test_cli_tts(seed_root, monkeypatch):
    from itcontent import paths

    monkeypatch.setattr(paths, "ROOT", seed_root)
    runner = CliRunner()
    res = runner.invoke(app, ["tts", "--provider", "mock", "--unit", "u02", "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "to render" in res.output and "$" in res.output
    res = runner.invoke(app, ["tts", "--provider", "mock", "--show", "u02.l1.story#3"])
    assert res.exit_code == 0, res.output
    assert '<voice name="it-IT-DiegoNeural">' in res.output  # Marco
    assert runner.invoke(app, ["tts", "--provider", "mock", "--show", "u02.l1.nothing"]).exit_code == 1


def test_the_mock_is_deterministic_and_answers_like_azure():
    ssml_ = (
        '<speak version="1.0" xml:lang="it-IT"><voice name="it-IT-ElsaNeural"><prosody rate="-10%">'
        "Scusi, quant&apos;è?</prosody></voice></speak>"
    )
    a = MockProvider().synthesize("job", [ssml_])[0]
    assert a.wav == render(ssml_).wav
    assert [b.text for b in a.boundaries] == ["Scusi", ",", "quant'è", "?"]
    assert a.boundaries[1].duration_ms == 0 and a.boundaries[2].offset_ms > a.boundaries[0].offset_ms
    assert read_wav_bytes(a.wav).samples > 0
