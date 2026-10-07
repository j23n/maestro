"""M1.6: chunk matching, item resolution, the lexical-article rule, disambiguation, line fields, lock files."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from conftest import needs_data
from itcontent import morphit
from itcontent.annotate import annotate_course, italian_options, lock_path, run_annotate
from itcontent.course import load_course
from itcontent.resolve import Ctx, Lexicon
from itcontent.tokenize import render

pytestmark = needs_data

EXTRA_ITEMS = {
    "w:porta~door": {"id": "w:porta~door", "it": "porta", "pos": "noun", "gender": "f", "plural": "porte"},
    "w:porta~verb": {"id": "w:porta~verb", "it": "portare", "pos": "verb", "forms": ["porta"]},
    "w:rosa": {"id": "w:rosa", "it": "rosa", "pos": "adj", "gender": "mf"},
    "w:signora": {"id": "w:signora", "it": "signora", "pos": "noun", "gender": "f", "plural": "signore"},
    "w:mangiare": {"id": "w:mangiare", "it": "mangiare", "pos": "verb"},
}


@pytest.fixture(scope="session")
def course(root):
    return load_course(root)


def make_lexicon(course, extra: dict | None = None) -> Lexicon:
    base = Lexicon.from_course(course, morphit.load())
    if not extra:
        return base
    items = {**base.items, **extra}
    return Lexicon(
        items=items,
        item_unit={**base.item_unit, **dict.fromkeys(extra, "u02")},
        unit_index=base.unit_index,
        point_unit=base.point_unit,
        allowlist=(course.singles["allowlist"].data or {}),
        disambiguation=(course.singles["disambiguation"].data or {}),
        morph=base.morph,
        detector=base.detector,
        intro=base.intro,
        slot_heads=base.slot_heads,
    )


@pytest.fixture(scope="session")
def lex(course):
    return make_lexicon(course, EXTRA_ITEMS)


def unit(lex: Lexicon, uid: str) -> int:
    return lex.unit_index[uid]


def ann(lex: Lexicon, text: str, uid: str = "u02", **kw):
    return lex.annotate(text, Ctx(unit=unit(lex, uid), pos=(unit(lex, uid), 1, 1), **kw))


def words(a) -> dict[str, tuple]:
    """surface → (item, chunk, sorted flags) for the non-punctuation tokens (last one wins on repeats)."""
    return {t.surface: (t.item, t.chunk, sorted(t.flags)) for t in a.tokens if t.kind != "punct"}


def errors(a) -> list[str]:
    return [i.message for i in a.issues if i.level == "error"]


# ---------------------------------------------------------------- chunks


def test_case_sensitive_chunk_e_lei(lex):
    a = ann(lex, "No, sono canadese. E Lei?")
    assert words(a)["E"][1] == words(a)["Lei"][1] == "c:e-lei"  # sentence-initial E still matches
    b = ann(lex, "Marco e lei sono di Bologna.")
    assert words(b)["e"] == ("w:e", None, []) and words(b)["lei"] == ("w:lei", None, [])
    c = ann(lex, "Marco e Lei sono di Bologna.")
    assert words(c)["Lei"][1] == "c:e-lei"
    assert words(ann(lex, "Le presento Sara.", "u01"))["Le"][1] == "c:le-presento"
    assert words(ann(lex, "Ti presento Sara.", "u01"))["Ti"][1] == "c:ti-presento"  # case-insensitive chunk


def test_longest_chunk_wins_and_punctuation_breaks_chunks(lex):
    a = ann(lex, "Come si chiama?")
    assert {t.chunk for t in a.tokens if t.kind == "word"} == {"c:come-si-chiama"}
    b = ann(lex, "Si chiama Aurora.")
    assert [t.chunk for t in b.tokens][:2] == ["c:come-si-chiama", "c:come-si-chiama"]
    c = ann(lex, "Scusi, quant'è?")
    assert [(t.surface, t.chunk) for t in c.tokens if t.kind == "word"] == [
        ("Scusi", "c:scusi"),
        ("quant'", "c:quant-e"),
        ("è", "c:quant-e"),
    ]
    d = ann(lex, "Per... favore!", strict=False)
    assert all(t.chunk is None for t in d.tokens)


def test_personal_slots_complete_chunks(lex):
    from itcontent.patterns import model_answer

    e = model_answer("Abito {ME.home}.")
    a = ann(lex, e.raw, "u01", protected=e.raw_slots)
    assert [(t.surface, t.kind, t.chunk) for t in a.tokens] == [
        ("Abito", "word", "c:abito"),
        ("{ME.home}", "slot", None),
        (".", "punct", None),
    ]
    assert not a.issues
    assert "in" in lex.slot_heads["ME.home"] and "negli" in lex.slot_heads["ME.home"]
    n = model_answer("mi chiamo {NAME}")
    b = ann(lex, n.raw, "u01", protected=n.raw_slots)
    assert [t.chunk for t in b.tokens[:2]] == ["c:mi-chiamo", "c:mi-chiamo"] and b.tokens[2].tok.slot == "NAME"
    c = model_answer("e {NAME}")  # a slot never completes a chunk it isn't the filler for
    assert ann(lex, c.raw, "u01", protected=c.raw_slots).tokens[0].item == "w:e"


# ---------------------------------------------------------------- item resolution


def test_surface_forms_resolve_first_and_keep_compatible_analyses(lex):
    w = {t.surface: t for t in ann(lex, "Grazie, un'amica e una spremuta.").tokens}
    assert w["amica"].item == "w:amico" and [str(x) for x in w["amica"].analyses] == ["amica NOUN-F:s"]
    assert [str(x) for x in w["Grazie"].analyses] == ["grazie INT"]  # not grazia NOUN-F:p
    sp = w["spremuta"]
    assert sp.item == "w:spremuta" and "synthetic" in sp.flags
    assert [str(x) for x in sp.analyses] == ["spremuta NOUN-F:s"]  # Morph-it!: only a participle of spremere
    pl = {t.surface: t for t in ann(lex, "Due spremute e due cornetti.").tokens}
    assert [str(x) for x in pl["spremute"].analyses] == ["spremuta NOUN-F:p"]  # the item's plural is a surface form
    assert pl["cornetti"].item == "w:cornetto"


def test_lemma_route_and_articles(lex):
    w = {t.surface: t for t in ann(lex, "Lei è italiana? Una spremuta!").tokens}
    assert w["italiana"].item == "w:italiano"  # Morph-it! lemma italiano, POS adj
    assert w["Una"].item == "g:indefinite-article"
    assert [str(x) for x in w["Una"].analyses] == ["una ART-F:s"]  # PRO-INDEF dropped
    d = ann(lex, "Il cornetto è buono.", "u03")
    assert d.tokens[0].item == "g:definite-article" and d.tokens[0].detections == ["g:definite-article"]
    e = ann(lex, "Al mercato.", "u07", strict=False)
    assert e.tokens[0].item == "g:articulated-prepositions"


def test_lexical_article_rule(lex):
    a = ann(lex, "Vorrei un cappuccino.", "u01")
    un = a.tokens[1]
    assert (un.item, un.head, sorted(un.flags), un.detections) == ("w:cappuccino", 2, ["lexical_article"], [])
    b = ann(lex, "Marco è in un bar.", "u01")  # an allowlisted noun counts
    assert "lexical_article" in b.tokens[3].flags and b.tokens[3].item is None and b.tokens[3].head == 4
    c = ann(lex, "Il bar.", "u02")  # Unit 2: il is lexical until Unit 3
    assert "lexical_article" in c.tokens[0].flags and not c.detections
    d = ann(lex, "Una buona spremuta.", "u01")  # article + adjective + noun item
    assert d.tokens[0].item == "w:spremuta" and d.tokens[0].head == 2
    d2 = ann(lex, "Un buon caffè.", "u01", strict=False)  # buon has its own lemma in Morph-it!: still an adjective
    assert d2.tokens[0].item == "w:caffe" and d2.tokens[0].head == 2
    e = ann(lex, "La signora Rossi.", "u01")
    assert e.tokens[0].item == "w:signora" and "lexical_article" in e.tokens[0].flags
    f = ann(lex, "Il cornetto.", "u03")  # from the article's own unit on, normal rules
    assert f.tokens[0].item == "g:definite-article" and "lexical_article" not in f.tokens[0].flags
    g = ann(lex, "Un cappuccino.", "u02")
    assert g.tokens[0].item == "g:indefinite-article" and g.tokens[0].detections == ["g:indefinite-article"]
    h = ann(lex, "Una, due, tre.", "u01")  # no noun: not lexical
    assert h.tokens[0].item == "g:indefinite-article"


def test_disambiguation_context_rules(lex):
    assert words(ann(lex, "Sei euro e venti."))["Sei"][0] == "w:sei"  # next: a plural noun analysis
    assert words(ann(lex, "Sei italiana?"))["Sei"][0] == "w:essere"
    assert words(ann(lex, "Tu sei di Bologna."))["sei"][0] == "w:essere"
    assert words(ann(lex, "Alle sei e venti.", strict=False))["sei"][0] == "w:sei"  # prev: alle
    assert words(ann(lex, "Uno, due, tre."))["Uno"][0] == "w:uno"
    uno = ann(lex, "Uno spremuta.").tokens[0]  # (bad Italian, but next is a noun: its item makes it one)
    assert uno.item == "g:indefinite-article"
    la = ann(lex, "La spremuta.", "u03").tokens[0]  # spremuta is only a participle in Morph-it!
    assert la.item == "g:definite-article"
    la = ann(lex, "La vedo.", "u07", strict=False).tokens[0]  # clitic: the pronoun reading, no item yet
    assert la.item is None and {x.category for x in la.analyses} == {"PRO-PERS-CLI-3-F-S"}
    assert any("untaught lemma 'la'" in m for m in errors(ann(lex, "La vedo.", "u07")))


def test_defaults_and_ambiguity_errors_name_the_candidates(course, lex):
    assert words(ann(lex, "Ecco la porta."))["porta"][0] == "w:porta~door"  # defaults: porta
    amb = make_lexicon(course, {"w:ecco~2": {"id": "w:ecco~2", "it": "ecco", "pos": "adv"}})
    a = ann(amb, "Ecco Sara.")
    assert a.tokens[0].item is None and a.tokens[0].candidates == ("w:ecco", "w:ecco~2")
    (msg,) = errors(a)
    assert "ambiguous 'Ecco': candidates w:ecco, w:ecco~2" in msg and "lemmas: {ecco:" in msg
    b = ann(amb, "Ecco Sara.", lemmas={"ecco": "w:ecco~2"})
    assert b.tokens[0].item == "w:ecco~2" and not b.issues
    assert any("unknown item w:nope" in m for m in errors(ann(lex, "Ecco.", lemmas={"ecco": "w:nope"})))
    assert any("lemmas key 'oggi'" in m for m in errors(ann(lex, "Ecco.", lemmas={"oggi": "w:oggi"})))


def test_names_are_case_sensitive_and_overridable(lex):
    a = ann(lex, "Rosa è rosa.", strict=False)
    assert [(t.surface, t.kind, t.item) for t in a.tokens if t.kind != "punct"] == [
        ("Rosa", "name", None),
        ("è", "word", "w:essere"),
        ("rosa", "word", "w:rosa"),
    ]
    b = ann(lex, "Rosa è il mio colore.", "u03", lemmas={"Rosa": "w:rosa"}, strict=False)
    assert (b.tokens[0].kind, b.tokens[0].item) == ("word", "w:rosa")


def test_unknown_tokens(lex):
    a = ann(lex, "Il gatto di Marco.", "u03")
    (msg,) = errors(a)
    assert "untaught lemma 'gatto' (token 'gatto')" in msg and "gloss it as new" in msg
    b = ann(lex, "Il gatto di Marco.", "u03", strict=False)
    assert not b.issues and "unresolved" in b.tokens[1].flags and b.tokens[1].lemma == "gatto"
    c = ann(lex, "Vorrei un cornettto.", strict=False)
    assert [i.level for i in c.issues] == ["warning"] and "typo" in c.issues[0].message
    d = ann(lex, "Mmm! Ah, buono.")
    assert not d.issues and "allowlisted" in d.tokens[0].flags


def test_line_fields_gloss_recognise_foreign(lex):
    a = ann(lex, "Un cappuccino. E da mangiare?", gloss={"da mangiare": "to eat"})
    da, mangiare = a.tokens[4], a.tokens[5]
    assert (da.chunk, da.gloss, sorted(da.flags)) == ("c:da-mangiare", "to eat", ["new"])
    assert mangiare.gloss == "to eat"
    # a glossed word with no item is new and fine; an item introduced earlier is glossed but not new
    b = ann(lex, "Il gatto di Marco.", "u03", gloss={"gatto": "cat", "di": "of"})
    assert not b.issues and "new" in b.tokens[1].flags and "new" not in b.tokens[2].flags
    c = ann(lex, "Il gatto dorme.", "u03", recognise=["dorme"], gloss={"gatto": "cat"})
    assert any("'dorme' needs a gloss" in m for m in errors(c))
    d = ann(lex, "Il gatto dorme.", "u03", recognise=["dorme"], gloss={"gatto": "cat", "dorme": "sleeps"})
    assert not d.issues and sorted(d.tokens[2].flags) == ["new", "recognise"]
    e = ann(lex, 'Come si dice "croissant"?', foreign=["croissant"])
    assert not e.issues and [t.kind for t in e.tokens if t.surface == "croissant"] == ["foreign"]
    assert any("gloss key 'tazza'" in m for m in errors(ann(lex, "Ecco.", gloss={"tazza": "cup"})))


def test_sound_words_and_pending_titles(lex):
    a = ann(lex, "eco", sound=True, sound_glosses={"eco": "echo"})
    assert not a.issues and a.tokens[0].gloss == "echo" and "sound" in a.tokens[0].flags
    b = ann(lex, "ecco", sound=True, sound_glosses={"ecco": "here is"})
    assert b.tokens[0].item == "w:ecco"
    c = ann(lex, "penna", sound=True)
    assert errors(c)
    d = ann(lex, "La famiglia", "u03", pending=True)
    assert [i.level for i in d.issues] == ["pending"] and "pending" in d.tokens[1].flags


def test_italian_options_rule():
    assert italian_options({"question_en": "How do you ask…?"}, "practice")
    assert not italian_options({"prompt_it": "Mmm! Buono!"}, "practice")
    assert not italian_options({"audio_text": {"lines": []}}, None)
    assert not italian_options({"source": {"text": "u02.task.menu"}}, None)
    assert not italian_options({}, "story")
    assert not italian_options({}, "listening")


# ---------------------------------------------------------------- the seed course and its lock files


@pytest.fixture(scope="session")
def result(course):
    return annotate_course(course, morphit.load())


def test_seed_course_annotates_without_errors(result):
    assert not result.errors, "\n".join(map(str, result.errors))
    assert not [f for f in result.findings if f.level == "warning"]


def test_golden_lesson_task_and_check_have_no_unknown_tokens(result):
    for rel in ["units/02-al-bar/lesson-1", "units/02-al-bar/task", "units/02-al-bar/check"]:
        lock = json.loads(result.locks[f"content/.annotations/{rel}.json"])
        for s in lock["strings"]:
            if s.get("model") is False:
                continue
            for t in s["tokens"]:
                if t["kind"] == "word":
                    resolved = (
                        t.get("item") or t.get("chunk") or {"allowlisted", "lexical_article"} & set(t.get("flags", []))
                    )
                    sound_ok = "sound" in t.get("flags", []) and t.get("gloss")
                    assert resolved or sound_ok, (rel, s["path"], t["surface"])


def test_golden_story_has_106_resolved_tokens(result):
    lock = json.loads(result.locks["content/.annotations/units/02-al-bar/lesson-1.json"])
    lines = [s for s in lock["strings"] if s["role"] == "line" and s["ref"].startswith("u02.l1.story#")]
    assert len(lines) == 22
    toks = [t for s in lines for t in s["tokens"] if t["kind"] != "punct"]
    assert len(toks) == 106
    assert all(t.get("item") or t.get("chunk") or t["kind"] in ("name", "foreign") or t.get("flags") for t in toks)
    da = [t for s in lines for t in s["tokens"] if t["surface"] == "da"]
    assert da[0]["flags"] == ["new"] and da[0]["gloss"] == "to eat"


def test_lock_files_re_render_and_spans(result):
    for path, text in result.locks.items():
        assert text.endswith("\n") and path.startswith("content/.annotations/")
        lock = json.loads(text)
        assert lock["format"] == 1 and lock_path(lock["source"]) == path
        for s in lock["strings"]:
            body = s.get("lead", "") + "".join(t["surface"] + t.get("trailing", "") for t in s["tokens"])
            assert body == s["text"], (path, s["path"])
            for t in s["tokens"]:
                assert s["text"][t["span"][0] : t["span"][1]] == t["surface"]


def test_pattern_and_cloze_entries(result):
    lock = json.loads(result.locks["content/.annotations/units/02-al-bar/lesson-1.json"])
    by = {}
    for s in lock["strings"]:
        by.setdefault(s["path"], []).append(s)
    ex06 = by["steps[3].block[5].answer"]
    assert [(e["expansion"], e["model"], e["norm"]) for e in ex06] == [
        (0, True, "una spremuta"),
        (1, False, "una spremuta d'arancia"),
    ]
    assert ex06[0]["focus"] == [1] and ex06[0]["pattern"] == "{una [spremuta]|una [spremuta] d'arancia}"
    (ex03,) = by["steps[3].block[2].text"]
    assert ex03["text"] == "Giulia è un'amica di Sara." and ex03["gap"] == [2, 2] and ex03["model"] is True
    assert ex03["tokens"][2]["surface"] == "un'"
    # near-miss answers are not annotated
    assert not [p for p in by if ".near" in p]
    # Italian choice options (ex17) yes, English comprehension options (q1) no
    assert "steps[3].mix[1].options[0]" in by and not [p for p in by if p.startswith("steps[1].questions")]
    # note fragments, cells; the *-o* ending is skipped
    frags = [s["text"] for s in lock["strings"] if s["role"] == "note"]
    assert "un'amica" in frags and "-o" not in frags and "caffè" in frags


def _copy_repo(root: Path, tmp: Path) -> Path:
    shutil.copytree(root / "content", tmp / "content", ignore=shutil.ignore_patterns(".annotations"))
    (tmp / "pipeline" / "data").mkdir(parents=True)
    (tmp / "pipeline" / "data" / "morph-it").symlink_to(root / "pipeline" / "data" / "morph-it")
    return tmp


def test_cli_writes_checks_and_names_stale_files(root, tmp_path):
    repo = _copy_repo(root, tmp_path)
    out: list[str] = []
    assert run_annotate(repo, check=True, echo=out.append) == 1
    assert any("lesson-1.json is missing" in x for x in out)
    out.clear()
    assert run_annotate(repo, echo=out.append) == 0
    assert run_annotate(repo, check=True, echo=out.append) == 0
    lesson = repo / "content/units/02-al-bar/lesson-1.yaml"
    lesson.write_text(lesson.read_text(encoding="utf-8").replace("Mmm! Buono!", "Mmm! Buono! Buono!"), "utf-8")
    (repo / "content/.annotations/units/zz.json").write_text("{}\n", encoding="utf-8")
    out.clear()
    assert run_annotate(repo, check=True, echo=out.append) == 1
    assert "error: content/.annotations/units/02-al-bar/lesson-1.json is stale: run `make annotate`" in out
    assert "error: content/.annotations/units/zz.json is left over: run `make annotate`" in out
    assert run_annotate(repo, echo=out.append) == 0 and not (repo / "content/.annotations/units/zz.json").exists()


def test_cli_errors_name_file_line_token_and_candidates(root, tmp_path):
    repo = _copy_repo(root, tmp_path)
    lesson = repo / "content/units/02-al-bar/lesson-1.yaml"
    text = lesson.read_text(encoding="utf-8").replace('"Sei euro e venti."', '"Sei euro e venti. Il gatto!"')
    lesson.write_text(text, encoding="utf-8")
    items = repo / "content/items/u02.yaml"
    items.write_text(
        items.read_text(encoding="utf-8")
        + "  - {id: 'w:ecco~2', it: ecco, pos: adv, gloss: lo!, status: P, lesson: u02.l2}\n",
        encoding="utf-8",
    )
    out: list[str] = []
    assert run_annotate(repo, echo=out.append) == 1
    line = next(i for i, x in enumerate(text.splitlines(), 1) if "Il gatto!" in x)
    gatto = [x for x in out if "'gatto'" in x]
    assert gatto and gatto[0].startswith(
        f"error: content/units/02-al-bar/lesson-1.yaml:{line} › steps[1].text.lines[19].it"
    )
    assert "untaught lemma 'gatto'" in gatto[0] and "'Sei euro e venti. Il gatto!'" in gatto[0]
    ecco = [x for x in out if "ambiguous 'Ecco'" in x]
    assert ecco and all("candidates w:ecco, w:ecco~2" in x for x in ecco)
    assert any(x.startswith("error: content/units/02-al-bar/lesson-1.yaml:") for x in ecco)
    assert out[-1].endswith("nothing written")
    assert not (repo / "content/.annotations").exists()


def test_committed_lock_files_are_fresh(root):
    out: list[str] = []
    assert run_annotate(root, check=True, echo=out.append) == 0, "\n".join(out)
    assert render("", []) == ""


def test_bad_detection_rules_are_reported_not_raised(course):
    import copy

    broken = copy.copy(course)
    broken.singles = dict(course.singles)
    det = copy.copy(course.singles["detection"])
    det.data = {"rules": [{"id": "g:x", "detect": [{"seq": [{"form": "("}]}]}]}
    broken.singles["detection"] = det
    res = annotate_course(broken, morphit.load())
    assert res.locks == {} and [f.file for f in res.errors] == ["content/grammar/detection.yaml"]
    assert "bad regex" in res.errors[0].message
