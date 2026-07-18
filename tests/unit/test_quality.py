"""Content-quality validators: precision-tuned warnings, not noise."""

from pathlib import Path

import pytest

from authoring.build_pack import load_pack_sources
from authoring.pack_schemas import (
    Answer,
    DrillItem,
    Evidence,
    Question,
    ReadingItem,
    SpeakingPromptItem,
    WritingPromptItem,
)
from authoring.quality import (
    Lemmatizer,
    check_adversarial,
    check_near_duplicates,
    check_orthography,
    check_solvability,
    check_vocab_level,
    validate_quality,
)
from authoring.validate_spec import load_spec

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
SPEC = load_spec(ROOT / "spec" / "it")

EV = [Evidence(axis="grammar", id="essere_pre", weight=1.0)]


def drill(prompt: str, answer: str, item_type: str = "drill_cloze", **kw) -> DrillItem:
    return DrillItem(
        id=kw.pop("id", "drill.essere_pre.901"),
        item_type=item_type,
        cefr_level="A0",
        prompt=prompt,
        answers=[Answer(text=answer, canonical=True)],
        evidence=EV,
        **kw,
    )


# ------------------------------------------------------------------ vocab


def test_vocab_level_flags_out_of_list_word():
    item = drill("Il ragno ___ velenoso.", "è")
    warnings = check_vocab_level([item], SPEC)
    flagged = " ".join(warnings.get(item.id, []))
    assert "ragno" in flagged  # spider is not in the A0 list
    assert "velenoso" in flagged


def test_vocab_level_accepts_in_level_and_glossed_and_proper_nouns():
    ok = drill("Anna ___ una amica.", "è", id="drill.essere_pre.902")
    warnings = check_vocab_level([ok], SPEC)
    assert warnings.get(ok.id) is None  # Anna = proper noun, rest in list

    reading = ReadingItem(
        id="reading.t.001",
        cefr_level="A0",
        title="t",
        text="Il ragno è qui.",
        glossary={"ragno": "spider"},
        questions=[
            Question(prompt="Dove è?", answers=[Answer(text="qui", canonical=True)])
        ],
        evidence=EV,
    )
    assert check_vocab_level([reading], SPEC).get(reading.id) is None


def test_vocab_level_lemmatizes_inflected_forms():
    # "parliamo" must resolve to lemma "parlare", which IS in the list.
    item = drill("Noi ___ italiano.", "parliamo", id="drill.ind_pres.903")
    warnings = check_vocab_level([item], SPEC)
    assert warnings.get(item.id) is None


def test_vocab_level_fake_lemmatizer_injectable():
    # "Xyzzy" is capitalized -> proper-noun rule skips it; "plugh" flags.
    item = drill("Xyzzy ___ plugh.", "è", id="drill.essere_pre.904")
    fake = Lemmatizer(lambda w: w)
    warnings = check_vocab_level([item], SPEC, fake)
    assert any("plugh" in w for w in warnings[item.id])


# ------------------------------------------------------------- solvability


def test_solvability_cloze_needs_blank():
    item = drill("Noi siamo qui.", "siamo")
    assert "no ___ blank" in check_solvability([item])[item.id][0]


def test_solvability_distractor_colliding_with_answer():
    item = drill(
        "Noi ___ qui.",
        "siamo",
        distractor_feedback={"Siamo": "not wrong at all"},
    )
    assert "accepted answer" in check_solvability([item])[item.id][0]


def test_solvability_mc_feedback_key_must_be_choice():
    item = drill(
        "Tu ___ qui.",
        "sei",
        item_type="drill_multiple_choice",
        choices=["sei", "siete"],
        distractor_feedback={"siete": "2nd plural", "sono": "not offered"},
    )
    msgs = check_solvability([item])[item.id]
    assert any("«sono»" in m for m in msgs)


def test_solvability_passage_answer_must_appear():
    reading = ReadingItem(
        id="reading.t.002",
        cefr_level="A0",
        title="t",
        text="Anna è al mare.",
        questions=[
            Question(
                prompt="Dove è Anna?", answers=[Answer(text="al mare", canonical=True)]
            ),
            Question(
                prompt="Come si chiama?",
                answers=[Answer(text="Beatrice", canonical=True)],
            ),
        ],
        evidence=EV,
    )
    msgs = check_solvability([reading])[reading.id]
    assert len(msgs) == 1 and "q2" in msgs[0]


def test_solvability_writing_model_answer_length():
    item = WritingPromptItem(
        id="writing.t.001",
        cefr_level="A0",
        prompt="Scrivi.",
        min_words=20,
        model_answer="Troppo corto.",
        evidence=EV,
    )
    assert "min_words" in check_solvability([item])[item.id][0]


def test_solvability_speaking_variant_duplicate():
    item = SpeakingPromptItem(
        id="speaking.t.001",
        cefr_level="A0",
        prompt="Saluta.",
        target_text="Ciao, sono Marco.",
        variants=["Ciao, sono Marco!"],
        evidence=EV,
    )
    assert "variant" in check_solvability([item])[item.id][0]


# ---------------------------------------------------------- near-duplicates


def test_near_duplicates_flags_close_prompts():
    a = drill("Noi ___ a Roma.", "siamo", id="drill.essere_pre.905")
    b = drill("Noi ___ a Roma!", "siamo", id="drill.essere_pre.906")
    c = drill("Voi ___ studenti universitari?", "siete", id="drill.essere_pre.907")
    warnings = check_near_duplicates([a, b, c])
    assert "near-duplicate of drill.essere_pre.905" in warnings[b.id][0]
    assert c.id not in warnings


# -------------------------------------------------------------- orthography


def test_orthography_elision_rules():
    bad = drill("Ecco la amica di Anna.", "è", id="drill.essere_pre.908")
    ok = drill("Ecco l'amica di Anna.", "è", id="drill.essere_pre.909")
    warnings = check_orthography([bad, ok])
    assert "l'amica" in warnings[bad.id][0]
    assert ok.id not in warnings


def test_orthography_un_apostrophe_before_consonant():
    bad = drill("Ho un'problema.", "ho", id="drill.essere_pre.910")
    warnings = check_orthography([bad])
    assert "un'" in warnings[bad.id][0]


# -------------------------------------------------------------- adversarial


def test_adversarial_pass_flags_defensible_alternates():
    item = drill("___ un caffè, per favore.", "Vorrei", id="drill.vorrei.901")

    def fake_model(prompt: str) -> str:
        assert "Vorrei" in prompt  # the item reached the model
        return (
            "```yaml\n"
            "- index: 1\n"
            '  alternates: ["Prendo"]\n'
            '  note: "Prendo is equally idiomatic when ordering"\n'
            "```"
        )

    warnings = check_adversarial([item], fake_model)
    assert "Prendo" in warnings[item.id][0]


def test_adversarial_pass_clean_key_is_silent():
    item = drill("Noi ___ qui.", "siamo", id="drill.essere_pre.911")
    warnings = check_adversarial([item], lambda _p: "```yaml\n[]\n```")
    assert warnings == {}


# ------------------------------------------------------------------- merge


def test_seed_pack_is_quality_clean():
    """The hand-checked seed content must not trip the checkers — that's
    the precision bar for every rule added here."""
    sources = load_pack_sources(ROOT / "packs" / "it")
    warnings = validate_quality(sources.all_items(), SPEC)
    assert warnings == {}, warnings
