"""Linking lesson text to the leveled vocabulary.

The interesting property is not recall, it's that a link is never wrong:
a word the learner didn't meet must never end up in their vocabulary.
"""

from pathlib import Path

import pytest

from authoring import vocab_link
from authoring.spec_schemas import VocabEntry
from authoring.validate_spec import load_spec

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def index():
    spec = load_spec(ROOT / "spec" / "it")
    return vocab_link.build_index(spec.vocab)[0]


def make_index(*lemmas: tuple[str, str]):
    """An index over just these (lemma, pos) pairs.

    The function words elision needs are being added to the spec
    separately; these tests state the rule rather than wait for them.
    """
    entries = [
        VocabEntry(id=lemma, cefr_level="A0", pos=pos, gloss="-") for lemma, pos in lemmas
    ]
    return vocab_link.build_index(entries)


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


def test_multiword_entries_still_win_around_an_elision(index):
    found = vocab_link.find_lemmas("Dov'è l'uscita, per favore?", index)
    assert "per favore" in found
    assert "dove" in found


def test_reports_words_in_order_of_first_appearance(index):
    found = vocab_link.find_lemmas("Grazie mille. Prego. Grazie.", index)
    assert found.index("grazie") < found.index("prego")
    assert found.count("grazie") == 1


def test_elided_articles_do_not_swallow_the_next_word(index):
    assert "acqua" in vocab_link.find_lemmas("Vorrei dell'acqua.", index)


def test_irregular_elisions_resolve_to_their_lemma(index):
    # The word carrying the meaning of "Dov'è ...?" is the one the
    # apostrophe used to orphan.
    assert "dove" in vocab_link.find_lemmas("Dov'è la stazione?", index)
    assert "quanto" in vocab_link.find_lemmas("Quant'è?", index)
    ci, _ = make_index(("ci", "pron"))
    assert vocab_link.find_lemmas("C'è un problema.", ci) == ["ci"]
    # "Che cos'è?" is the whole of the che_cose grammar point, and the
    # unelided "cosa è" is the form nobody says.
    idx, _ = make_index(("cosa", "pron"), ("anche", "adv"))
    assert vocab_link.find_lemmas("Che cos'è? Anch'io.", idx) == ["cosa", "anche"]


def test_article_elisions_fall_out_of_surface_generation():
    forms = vocab_link.surface_forms("una", "art")
    assert "un'" in forms
    assert vocab_link.surface_forms("della", "prep") == {"della", "dell'"}
    # Articles are invariable: no noun/adjective plurals get invented.
    assert vocab_link.surface_forms("la", "art") == {"la", "l'"}


def test_an_elided_article_links_the_word_it_precedes():
    idx, _ = make_index(("una", "art"), ("amica", "noun"), ("acqua", "noun"))
    assert vocab_link.find_lemmas("Un'amica beve l'acqua.", idx) == ["una", "amica", "acqua"]


def test_l_apostrophe_is_dropped_rather_than_guessed():
    # "l'" is the elision of both "il" and "la"; the index refuses to pick.
    idx, ambiguous = make_index(("il", "art"), ("la", "art"), ("acqua", "noun"))
    assert "l'" in ambiguous
    assert "l'" not in idx
    # The half that matters still works: the noun after it is linked.
    assert vocab_link.find_lemmas("Bevo l'acqua.", idx) == ["acqua"]


def test_a_trailing_apostrophe_is_truncation_not_elision(index):
    # "un po'" drops a syllable; the apostrophe is not eliding anything,
    # so the token is still "po" and "parlare" is still found.
    assert "parlare" in vocab_link.find_lemmas("Parlo un po' di italiano.", index)


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
