"""The closure contract (docs/plans/07 §3).

Built around one fully-compliant scenario rather than the real spec: the
real spec has no `introduces` blocks yet, so it fails every rule, and a
test that only ever sees failure never proves the rules can be satisfied.
"""

import pytest

from authoring.coverage import check_coverage, check_unlinked_words
from authoring.pack_schemas import (
    Answer,
    DrillItem,
    Evidence,
    GrammarRefItem,
    SpeakingPromptItem,
    TaskItem,
    VocabCardItem,
)
from authoring.spec_schemas import (
    CanDo,
    CommunicativeFunction,
    GrammarPoint,
    Scenario,
    Spec,
    VocabEntry,
)

pytestmark = pytest.mark.unit

GP, CF, LEMMA, CANDO = "vorrei", "a0_ordinare", "caffè", "a0.order_something"


def _spec(depths) -> Spec:
    return Spec(
        language="it",
        grammar_points=[
            GrammarPoint(id=GP, cefr_level="A0", category="verbi", label="vorrei")
        ],
        communicative_functions=[
            CommunicativeFunction(
                id=CF, cefr_level="A0", category="c", label="ordinare"
            )
        ],
        vocab=[VocabEntry(id=LEMMA, cefr_level="A0", pos="noun", gloss="coffee")],
        can_dos=[
            CanDo(
                id=CANDO,
                cefr_level="A0",
                skill="spoken_interaction",
                label="Can order a coffee.",
                theme="services",
                grammar_ids=[GP],
                function_ids=[CF],
                scenario_ids=["al-bar"],
            )
        ],
        scenarios=[
            Scenario(
                id="al-bar",
                cefr_level="A0",
                label="Al bar",
                description="Coffee, standing up",
                depths=depths,
            )
        ],
    )


def _compliant_depths():
    """One home and two rising revisits for every axis."""
    return [
        {
            "id": "al-bar.d1",
            "introduces": {"grammar": [GP], "functions": [CF], "vocab": [LEMMA]},
            "capstones": [{"cando": CANDO, "demand": "use"}],
        },
        {
            "id": "al-bar.d2",
            "revisits": {
                "grammar": [{"id": GP, "demand": "use"}],
                "functions": [{"id": CF, "demand": "use"}],
                "vocab": [{"id": LEMMA, "demand": "use"}],
            },
            "capstones": [{"cando": CANDO, "demand": "use"}],
        },
        {
            "id": "al-bar.d3",
            "revisits": {
                "grammar": [{"id": GP, "demand": "perform"}],
                "functions": [{"id": CF, "demand": "perform"}],
                "vocab": [{"id": LEMMA, "demand": "perform"}],
            },
            "capstones": [{"cando": CANDO, "demand": "perform"}],
        },
    ]


def _items():
    ev_g = [Evidence(axis="grammar", id=GP)]
    items = [
        GrammarRefItem(
            id="grammar_ref.vorrei",
            cefr_level="A0",
            grammar_id=GP,
            title="Vorrei",
            body_md="...",
            evidence=ev_g,
            lesson_id="al-bar.d1",
        ),
        SpeakingPromptItem(
            id="speaking.ordinare.001",
            cefr_level="A0",
            prompt="Ordina un caffè.",
            target_text="Vorrei un caffè, per favore.",
            evidence=[Evidence(axis="function", id=CF)],
            lesson_id="al-bar.d1",
        ),
        VocabCardItem(
            id="vocab.caffe",
            cefr_level="A0",
            lemma=LEMMA,
            front="caffè",
            back="coffee",
            evidence=[Evidence(axis="vocab", id=LEMMA)],
            lesson_id="al-bar.d1",
        ),
    ]
    items += [
        DrillItem(
            id=f"drill.vorrei.{n:03d}",
            item_type="drill_cloze",
            cefr_level="A0",
            prompt="___ un caffè.",
            answers=[Answer(text="Vorrei", canonical=True)],
            evidence=ev_g,
            lesson_id="al-bar.d1",
        )
        for n in range(1, 7)
    ]
    # A capstone per lesson that declares one. The last carries every axis
    # at `perform`, which is what satisfies the global supply rule.
    for depth, demand in (("d1", "use"), ("d2", "use"), ("d3", "perform")):
        evidence = [Evidence(axis="cando", id=CANDO)]
        if demand == "perform":
            evidence += [
                Evidence(axis="grammar", id=GP),
                Evidence(axis="function", id=CF),
                Evidence(axis="vocab", id=LEMMA),
            ]
        items.append(
            TaskItem(
                id=f"task.al_bar.{depth}",
                cefr_level="A0",
                demand=demand,
                mode="speaking",
                prompt="Ordina per tutti e due.",
                target_text="Vorrei due caffè, per favore.",
                rubric=["orders for two"],
                evidence=evidence,
                lesson_id=f"al-bar.{depth}",
            )
        )
    return items


def spiral(spec, items, **kw):
    """The spiral rules only.

    The fixture's Italian text deliberately uses words its one-lemma
    vocabulary does not contain, so `unlinked-word` fires on every call.
    That rule is a different property with its own tests below; mixing the
    two would make every spiral assertion depend on the fixture's prose.
    """
    report = check_coverage(spec, items, **kw)
    report.findings = [f for f in report.findings if f.rule != "unlinked-word"]
    return report


def test_a_fully_spiralled_scenario_satisfies_the_contract():
    report = spiral(_spec(_compliant_depths()), _items())
    assert report.findings == [], report.summary()
    assert report.covered == {"grammar": 1, "function": 1, "vocab": 1, "cando": 1}
    assert report.lessons == 3


def test_teaching_something_once_is_not_covering_it():
    """The whole point of the spiral: a single lesson is not enough, even
    when that lesson is complete."""
    depths = _compliant_depths()
    depths[1]["revisits"] = {}
    depths[2]["revisits"] = {}
    rules = {f.rule for f in spiral(_spec(depths), _items()).findings}
    assert "too-few-passes" in rules
    assert "never-performed" in rules


def test_a_revisit_may_not_go_down_a_rung():
    depths = _compliant_depths()
    depths[1]["revisits"]["grammar"] = [{"id": GP, "demand": "perform"}]
    depths[2]["revisits"]["grammar"] = [{"id": GP, "demand": "use"}]
    findings = spiral(_spec(depths), _items()).findings
    assert {f.rule for f in findings} >= {"falling-demand", "never-performed"}


def test_two_homes_is_as_broken_as_none():
    """An ambiguous home means two lessons each think they teach it, so
    whichever runs second re-teaches material the learner has met."""
    depths = _compliant_depths()
    depths[1]["introduces"] = {"grammar": [GP]}
    rules = [f.rule for f in spiral(_spec(depths), _items()).findings]
    assert "ambiguous-home" in rules

    depths = _compliant_depths()
    depths[0]["introduces"] = {"functions": [CF], "vocab": [LEMMA]}
    rules = [f.rule for f in spiral(_spec(depths), _items()).findings]
    assert "orphan" in rules


def test_a_home_owes_the_material_it_introduces():
    """Declaring a home is a promise the pack has to keep."""
    items = [i for i in _items() if not i.id.startswith("grammar_ref")]
    findings = spiral(_spec(_compliant_depths()), items).findings
    assert [f.rule for f in findings] == ["home-missing-reference"]

    items = [i for i in _items() if not i.id.startswith("drill.")]
    findings = spiral(_spec(_compliant_depths()), items).findings
    assert [f.rule for f in findings] == ["home-missing-drills"]


def test_a_capstone_without_a_task_cannot_achieve_anything():
    """The finding that would have caught the live bug: every can-do in
    the shipped spec is unreachable because no item carries axis cando."""
    items = [i for i in _items() if not i.id.startswith("task.")]
    rules = {f.rule for f in spiral(_spec(_compliant_depths()), items).findings}
    assert "missing-capstone-task" in rules
    assert "no-perform-supply" in rules


def test_declaring_perform_without_authoring_it_is_caught():
    """A lesson can promise a rung the pack has no item for. Rule 4's
    second half is the global supply check that catches it.

    The closing capstone stays in place, so the can-do is fully covered —
    it is the three axes the capstone stopped carrying that fall through.
    """
    items = [
        i.model_copy(update={"evidence": [Evidence(axis="cando", id=CANDO)]})
        if i.id == "task.al_bar.d3"
        else i
        for i in _items()
    ]
    findings = spiral(_spec(_compliant_depths()), items).findings
    assert {f.rule for f in findings} == {"no-perform-supply"}
    assert {f.axis for f in findings} == {"grammar", "function", "vocab"}


def test_draft_items_are_not_supply_unless_asked_for():
    drafts = [i.model_copy(update={"status": "draft"}) for i in _items()]
    spec = _spec(_compliant_depths())
    assert spiral(spec, drafts).findings != []
    assert (
        spiral(spec, drafts, statuses=frozenset({"reviewed", "draft"})).findings == []
    )


# --------------------------------------------------------------------------
# The word chain: lesson text -> surface form -> lemma -> dictionary entry.


def test_every_italian_word_must_resolve_to_a_dictionary_entry():
    """A word that resolves to nothing never enters the learner's
    vocabulary, never gets a gloss, and cannot be looked up. It is just a
    word on screen the app knows nothing about."""
    items = _items()
    findings = check_unlinked_words(_spec(_compliant_depths()), items)
    unlinked = {f.id for f in findings}
    # The fixture's prose uses words its one-lemma vocabulary lacks.
    assert "vorrei" in unlinked
    assert all(f.rule == "unlinked-word" for f in findings)
    # And it says where, so the gap is actionable rather than a count.
    assert any("speaking.ordinare.001" in f.detail for f in findings)

    # A proper noun is known-but-not-vocabulary: excused by name.
    excused = check_unlinked_words(
        _spec(_compliant_depths()), items, proper_nouns={"vorrei"}
    )
    assert "vorrei" not in {f.id for f in excused}


def test_a_word_in_the_dictionary_resolves():
    spec = _spec(_compliant_depths())
    spec.vocab.append(
        VocabEntry(id="vorrei", cefr_level="A0", pos="verb", gloss="I would like")
    )
    assert "vorrei" not in {f.id for f in check_unlinked_words(spec, _items())}


def test_grammatical_words_need_a_gloss_but_not_a_flashcard():
    """`il` is taught by the grammar point that uses it, not by a card
    reading "il -> the". It needs a dictionary entry and to resolve;
    it does not need a home lesson, three passes, or SRS material."""
    spec = _spec(_compliant_depths())
    spec.vocab.append(
        VocabEntry(id="il", cefr_level="A0", pos="art", gloss="the (masculine)")
    )
    report = spiral(spec, _items())
    assert report.findings == [], report.summary()
    # Counted as covered on the strength of having an entry at all.
    assert report.covered["vocab"] == 2

    # A content word with the same (absent) treatment is still an orphan.
    spec.vocab.append(
        VocabEntry(id="tavolo", cefr_level="A0", pos="noun", gloss="table")
    )
    rules = {f.rule for f in spiral(spec, _items()).findings}
    assert "orphan" in rules
