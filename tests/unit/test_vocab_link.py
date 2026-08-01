"""Linking lesson text to the leveled vocabulary.

The interesting property is not recall, it's that a link is never wrong:
a word the learner didn't meet must never end up in their vocabulary.
"""

from pathlib import Path

import pytest

from authoring import vocab_link
from authoring.validate_spec import load_spec

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def index():
    spec = load_spec(ROOT / "spec" / "it")
    return vocab_link.build_index(spec.vocab)[0]


def test_matches_inflected_forms_not_just_citation_forms(index):
    found = vocab_link.find_lemmas(
        "L'assistente di volo arriva. Buongiorno! Desidera un caffè?", index
    )
    assert "arrivare" in found, "regular -are present tense"
    assert "buongiorno" in found
    assert "caffè" in found


def test_matches_irregular_verbs(index):
    found = vocab_link.find_lemmas(
        "Mi chiamo Anna e sono di Roma. Ho una camera.", index
    )
    assert "essere" in found
    assert "avere" in found


def test_matches_multiword_entries_as_one_word(index):
    found = vocab_link.find_lemmas("Un caffè, per favore.", index)
    assert "per favore" in found


def test_reports_words_in_order_of_first_appearance(index):
    found = vocab_link.find_lemmas("Grazie mille. Prego. Grazie.", index)
    assert found.index("grazie") < found.index("prego")
    assert found.count("grazie") == 1


def test_elided_articles_do_not_swallow_the_next_word(index):
    assert "acqua" in vocab_link.find_lemmas("Vorrei dell'acqua.", index)


def test_ambiguous_forms_are_dropped_rather_than_guessed(index):
    # "saluti" is both the plural of the noun and the 2sg of salutare;
    # "stato" is both the noun and essere's participle. Neither may resolve.
    assert "saluti" not in index
    assert "stato" not in index
    assert vocab_link.find_lemmas("Tanti saluti!", index) == []


def test_a_lemmas_own_citation_form_outranks_another_lemmas_inflection(index):
    # `portare` would generate "porta"; the noun must keep its own form.
    if "porta" in index:
        assert index["porta"] == "porta"


def test_generated_forms_never_invent_a_lemma(index):
    spec = load_spec(ROOT / "spec" / "it")
    known = {v.id for v in spec.vocab}
    assert set(index.values()) <= known


def test_only_quoted_italian_is_taken_from_mixed_prose():
    # Instruction prose is English, and "come"/"no"/"male" are spec lemmas.
    assert vocab_link.quoted_spans("Come back later. «Come stai?»") == ["Come stai?"]


def test_english_instructions_contribute_nothing(index):
    prompt = "You are leaving the hotel at midnight. What do you say?"
    text = "\n".join(vocab_link.quoted_spans(prompt))
    assert vocab_link.find_lemmas(text, index) == []
