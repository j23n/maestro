"""The text checker and briefs for German: du and Sie, prefixed grammar topics, German form topics."""

import os

import pytest

from maestro_content import build_db, curriculum, kaikki
from maestro_content.registry import Registry

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DE = os.path.join(ROOT, "content", "de")


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("de")
    conn = build_db.create(str(tmp / "content.sqlite"), os.path.join(ROOT, "content", "schema", "content.sql"))
    entries, form_of = kaikki.read(kaikki.open_jsonl(os.path.join(HERE, "fixtures", "kaikki-sample-de.jsonl")), "de")
    build_db.build(conn, entries, form_of, Registry(language="de"))
    folder = tmp / "texts" / "test"
    folder.mkdir(parents=True)
    (folder / "test-01.md").write_text(
        "# Test\nlevel: A1\ncollection: test\norder: 1\nintroduces: perfekt\nregister: tu\n\n"
        "Ich habe gestern mit dem Lehrer gegessen. || Yesterday I ate with the teacher.\n"
        "Die Frau ist zum Bahnhof gegangen. || The woman went to the station.\n"
        "Er hat das Haus gekauft. || He bought the house.\n"
        "Morgen werde ich nach Hause fahren. || Tomorrow I'll go home.\n", encoding="utf-8")
    freq = tmp / "freq.txt"
    freq.write_text("ich 100\n", encoding="utf-8")
    library = curriculum.load_library(conn, str(tmp / "texts"), os.path.join(DE, "curriculum"),
                                      os.path.join(DE, "grammar"), str(freq), language="de")
    return conn, library


def test_german_rules(lib):
    _, library = lib
    text = library.texts[0]
    assert text.language == "de" and text.brief_topics("introduces") == ["de:perfekt"]
    assert text.uses("de:perfekt") >= 3, "three Perfekt units"
    findings = curriculum.check_text(library, text)
    assert not [f for f in findings if f.check == "brief" and "perfekt" in f.message]
    register = [f.message for f in findings if f.check == "register"]
    assert register == ["register must be du or Sie, not 'tu'"]
    above = [f.message for f in findings if f.check == "above-level grammar"]
    assert above == ["ind.fut1 (A2) used 1 times; it is taught at A2"], "Futur I comes at A2"


def test_brief_names_topics_without_the_prefix(lib):
    conn, library = lib
    _, content = curriculum.propose_brief(library, conn, "A1", "test", "Neu")
    meta = dict(line.split(": ", 1) for line in content.splitlines()[1:] if ": " in line)
    assert meta["introduces"] and not meta["introduces"].startswith("de:")
    assert meta["register"] in ("du", "Sie")
