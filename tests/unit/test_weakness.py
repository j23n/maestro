"""Unit tests for maestro.learning.weakness tooltip helpers."""

from types import SimpleNamespace

import pytest

from maestro.learning.weakness import build_tooltip_data
from maestro.models import Explanation


def _item(code, tip="", examples=None, expl_lang="en", explanations=None):
    """Build a mock item matching GrammarPoint/CommunicativeFunction interface."""
    if explanations is None:
        if tip or expl_lang:
            explanations = {
                expl_lang: Explanation(
                    title=f"Title for {code}",
                    tip=tip,
                    explanation=f"Full explanation for {code}",
                    language=expl_lang,
                )
            }
        else:
            explanations = {}
    return SimpleNamespace(
        code=code,
        label=f"Label {code}",
        examples=examples or [],
        explanations=explanations,
    )


@pytest.mark.unit
def test_tip_and_examples():
    item = _item("gp1", tip="Use this form.", examples=["Ciao", "Buongiorno"])
    result = build_tooltip_data([item], cefr="A1", target_language="it")
    assert result == {
        "gp1": {"tip": "Use this form.", "examples": ["Ciao", "Buongiorno"]},
    }


@pytest.mark.unit
def test_examples_no_tip():
    item = _item("gp1", tip="", examples=["Hallo", "Tschüss"])
    result = build_tooltip_data([item], cefr="A1", target_language="de")
    assert result["gp1"]["tip"] == ""
    assert result["gp1"]["examples"] == ["Hallo", "Tschüss"]


@pytest.mark.unit
def test_no_explanations_uses_item_examples():
    item = _item("gp1", explanations={}, examples=["Bonjour"])
    result = build_tooltip_data([item], cefr="A1", target_language="fr")
    assert result["gp1"]["tip"] == ""
    assert result["gp1"]["examples"] == ["Bonjour"]


@pytest.mark.unit
def test_no_explanations_no_examples():
    item = _item("gp1", explanations={}, examples=[])
    result = build_tooltip_data([item], cefr="A1", target_language="it")
    assert result == {}


@pytest.mark.unit
def test_empty_items():
    assert build_tooltip_data([], cefr="A1", target_language="it") == {}


@pytest.mark.unit
def test_lang_fallback():
    """When primary explanation lang is missing, falls back to the other."""
    # A1 → primary lang is "en", fallback is target language
    item = _item("gp1", tip="Usa questo.", expl_lang="it")
    result = build_tooltip_data([item], cefr="A1", target_language="it")
    assert result["gp1"]["tip"] == "Usa questo."


@pytest.mark.unit
def test_strips_lang_spans():
    item = _item(
        "gp1",
        tip='Use <span lang="it">ciao</span> to greet.',
        examples=['<span lang="it">Ciao mondo</span>'],
    )
    result = build_tooltip_data([item], cefr="A1", target_language="it")
    assert result["gp1"]["tip"] == "Use ciao to greet."
    assert result["gp1"]["examples"] == ["Ciao mondo"]


@pytest.mark.unit
def test_max_three_examples():
    item = _item("gp1", tip="x", examples=["a", "b", "c", "d", "e"])
    result = build_tooltip_data([item], cefr="A1", target_language="it")
    assert len(result["gp1"]["examples"]) == 3
