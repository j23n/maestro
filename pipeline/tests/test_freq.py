"""M1.12: `content freq` and `content suggest` with a small frequency fixture.

`tests/fixtures/frequency/it-mini.txt` is in the FrequencyWords format (`form count`, most frequent first) with made-up
counts, one repeated form (`casa`: the first line wins) and one malformed line (skipped). Lemmas come from the real
Morph-it! (`make data`); the real list is `pipeline/data/frequency/it_50k.txt`. The course is the frozen seed course
(conftest), so the items it covers don't change as the course grows.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import needs_data
from itcontent import morphit
from itcontent.cli import app
from itcontent.course import load_course
from itcontent.freq import Frequency, category_pos, covered, run_freq, run_suggest, suggest

pytestmark = needs_data


@pytest.fixture(scope="module")
def mini(fixtures_dir: Path) -> Path:
    return fixtures_dir / "frequency" / "it-mini.txt"


@pytest.fixture(scope="module")
def lemmas(mini: Path):
    return Frequency.load(mini).lemmas(morphit.load())


def test_frequency_list_ranks_forms(mini):
    freq = Frequency.load(mini)
    assert freq.by_form["e"].rank == 1 and freq.by_form["caffè"].rank == 9
    assert freq.by_form["casa"].count == 250  # a repeated form keeps its first line
    assert freq.by_form["marco"].form == "marco"  # forms are folded to lowercase
    assert len(freq.forms) == 21  # the malformed line is skipped


def test_forms_group_into_lemmas(lemmas):
    assert lemmas["essere"].count == 700 + 650  # è, sono
    assert lemmas["avere"].count == 500 + 450  # ho, ha
    assert lemmas["casa"].count == 250 + 120 and "noun" in lemmas["casa"].pos
    assert lemmas["mangiare"].count == 300 and lemmas["mangiare"].pos == {"verb"}
    assert lemmas["essere"].rank < lemmas["avere"].rank < lemmas["casa"].rank
    assert "la" not in lemmas  # also an article: a grammar point, never an item
    assert "xyzzy" not in lemmas  # unknown to Morph-it!
    assert category_pos("ARTPRE-M") is None and category_pos("DET-NUM-CARD") == "num" and category_pos("AUX") == "verb"


def test_suggest_leaves_out_items_and_allowlisted_words(seed_root, lemmas):
    cov = covered(load_course(seed_root), seed_root)
    rows = [lem.lemma for lem in suggest(lemmas, cov)]
    # essere, e, non, di, caffè and latte are items; Marco and bar are allowlisted
    assert rows[:3] == ["avere", "casa", "mangiare"]
    assert not {"essere", "e", "non", "di", "caffè", "latte", "marco", "bar"} & set(rows)
    assert [lem.lemma for lem in suggest(lemmas, cov, pos="noun")][:4] == ["casa", "mamma", "madre", "padre"]
    assert [lem.lemma for lem in suggest(lemmas, cov, words=["pane", "latte", "case"])] == ["casa", "pane"]
    assert [lem.lemma for lem in suggest(lemmas, cov, limit=2)] == ["avere", "casa"]


def test_freq_command(seed_root, mini):
    out: list[str] = []
    assert run_freq(["caffè", "sono", "xyzzy", "zzz"], root=seed_root, freq_file=mini, echo=out.append) == 0
    assert out[0] == "caffè: form rank 9 (300); lemma caffè (noun): rank 7 (300), item w:caffe (u02)"
    assert (
        out[1].startswith("sono: form rank 5 (650); lemma essere (") and "rank 1 (1,350), item w:essere (u01)" in out[1]
    )
    assert out[2] == "xyzzy: form rank 20 (40); no Morph-it! lemma (a name, a foreign word or a typo?)"
    assert out[3] == "zzz: form not in the list; no Morph-it! lemma (a name, a foreign word or a typo?)"


def test_suggest_command(seed_root, mini):
    out: list[str] = []
    assert run_suggest(unit="u07", topic="topic:food-drink", root=seed_root, freq_file=mini, echo=out.append) == 0
    text = "\n".join(out)
    assert out[0] == "# Item candidates for u07 · topic:food-drink"
    assert "Items with topic:food-drink so far: w:arancia (u02), w:buono (u02), w:caffe (u02)" in text
    assert "| 3 | avere | verb | 950 | ho, ha |  |" in text
    assert "| 6 | casa | noun | 370 | casa, case | yes |" in text  # the unit title "Casa mia" uses it (pending)
    assert "marcare" not in text  # its top form is the allowlisted name Marco
    out.clear()
    assert run_suggest(unit="u07", words=["pane", "latte"], root=seed_root, freq_file=mini, echo=out.append) == 0
    assert out[-1] == "Already items, allowlisted or not in the list: latte"
    assert run_suggest(unit="u42", root=seed_root, freq_file=mini, echo=out.append) == 2
    assert run_suggest(unit="u07", pos="verbo", root=seed_root, freq_file=mini, echo=out.append) == 2


def test_cli_and_missing_data(seed_root, mini, tmp_path, monkeypatch):
    from itcontent import paths

    monkeypatch.setattr(paths, "ROOT", seed_root)
    result = CliRunner().invoke(app, ["freq", "casa", "--freq", str(mini)])
    assert result.exit_code == 0 and result.output.startswith("casa: form rank 10 (250); lemma casa (")
    result = CliRunner().invoke(app, ["suggest", "--unit", "u03", "--pos", "noun", "--limit", "3", "--freq", str(mini)])
    assert result.exit_code == 0 and "| casa |" in result.output
    out: list[str] = []
    assert run_freq(["casa"], root=seed_root, freq_file=tmp_path / "none.txt", echo=out.append) == 2
    assert out == [f"error: {tmp_path / 'none.txt'} is missing: run `make data`"]
