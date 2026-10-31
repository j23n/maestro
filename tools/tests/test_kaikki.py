import os

from maestro_content import kaikki

SAMPLE = os.path.join(os.path.dirname(__file__), "fixtures", "kaikki-sample.jsonl")


def _read():
    return kaikki.read(kaikki.open_jsonl(SAMPLE))


def test_entries_and_forms():
    entries, form_of = _read()
    by = {(e.headword, e.etymology): e for e in entries}
    andare = by[("andare", "")]
    assert andare.pos == "v" and andare.auxiliary == "essere" and andare.ipa == "/anˈda.re/"
    forms = dict((f, t) for f, t in andare.forms if t.startswith("ind."))
    assert forms["andavamo"] == "ind.impf.1p" and forms["andò"] == "ind.prem.3s"
    assert ("va'", "imp.pres.2s") in andare.forms
    assert not any(" " in f for f, _ in andare.forms), "multiword forms are dropped"
    assert not any(f == "andàre" for f, _ in andare.forms), "canonical head forms are dropped"
    assert [s.gloss for s in andare.senses][:2] == ["to go", "to work, to function"]
    assert andare.senses[2].senseid == "it:leave"
    assert by[("correre", "")].auxiliary == "both"
    assert by[("nonno", "")].gender == "m" and by[("nonno", "")].plural == "nonni"
    assert {by[("pesca", "1")].senses[0].gloss, by[("pesca", "2")].senses[0].gloss} == {"peach", "fishing"}
    assert all(e.headword != "house" for e in entries), "other languages are skipped"
    assert any(fo.form == "andavamo" and fo.lemma == "andare" and fo.tag == "ind.impf.1p" for fo in form_of)
