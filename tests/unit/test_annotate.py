"""Unit tests for vocab.annotate — verified lemma annotation."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from maestro.models import ActivityType, VocabAnnotation
from maestro.vocab import cache as _vocab_cache
from maestro.vocab.annotate import (
    _validate_tokens,
    annotate_lesson_activities,
    annotate_texts,
)

pytestmark = pytest.mark.unit


def _word(headword, pos="v.tr."):
    return SimpleNamespace(word=headword, part_of_speech=pos, id=headword)


@pytest.fixture(autouse=True)
def vocab_cache():
    _vocab_cache.seed(
        words={
            "mangiare": [_word("mangiare")],
            "pizza": [_word("pizza", "s.f.")],
            "capire": [_word("capire")],
        },
        defs={},
        phrases={"un po'": [_word("un po'", "avv.")]},
        language="it",
    )
    yield
    _vocab_cache.invalidate("it")


def test_validate_keeps_only_word_index_lemmas():
    tokens = [
        {"surface": "mangio", "lemma": "mangiare", "upos": "VERB"},
        # spaCy's classic failure — LLM said capiscare, not in dictionary
        {"surface": "capisco", "lemma": "capiscare", "upos": "VERB"},
    ]
    result = _validate_tokens(tokens, "Mangio e capisco.", "it")
    assert [a.lemma for a in result] == ["mangiare"]


def test_validate_requires_surface_in_text():
    tokens = [{"surface": "pizza", "lemma": "pizza", "upos": "NOUN"}]
    assert _validate_tokens(tokens, "Mangio un panino.", "it") == []
    # Substring is not enough — word boundaries required
    assert _validate_tokens(tokens, "La pizzeria è chiusa.", "it") == []


def test_validate_accepts_phrase_index_lemmas():
    tokens = [{"surface": "un po'", "lemma": "un po'", "upos": "ADV"}]
    result = _validate_tokens(tokens, "Mangio un po' di pizza.", "it")
    assert [a.lemma for a in result] == ["un po'"]


def test_validate_merges_surfaces_for_same_lemma():
    tokens = [
        {"surface": "mangio", "lemma": "mangiare", "upos": "VERB"},
        {"surface": "mangiamo", "lemma": "mangiare", "upos": "VERB"},
        {"surface": "mangio", "lemma": "mangiare", "upos": "VERB"},
    ]
    result = _validate_tokens(tokens, "Io mangio, noi mangiamo.", "it")
    assert len(result) == 1
    assert result[0].surface_forms == ["mangio", "mangiamo"]


def _llm_response(payload):
    return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])


async def test_annotate_texts_aligns_results_with_inputs():
    payload = {
        "texts": [
            {
                "index": 1,
                "tokens": [{"surface": "pizza", "lemma": "pizza", "upos": "NOUN"}],
            }
        ]
    }
    with patch(
        "maestro.vocab.annotate.llm_messages_create",
        new_callable=AsyncMock,
        return_value=_llm_response(payload),
    ):
        result = await annotate_texts(
            ["Testo senza token.", "Una pizza buona."], language="it"
        )
    assert result is not None
    assert result[0] == []
    assert [a.lemma for a in result[1]] == ["pizza"]


async def test_annotate_texts_returns_none_on_llm_failure():
    with patch(
        "maestro.vocab.annotate.llm_messages_create",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        assert await annotate_texts(["Una pizza."], language="it") is None


async def test_annotate_texts_returns_none_without_word_index():
    _vocab_cache.invalidate("it")
    _vocab_cache.seed(words={}, defs={}, language="it")
    assert await annotate_texts(["Una pizza."], language="it") is None


def _activity(**kw):
    defaults = dict(
        type=ActivityType.READING,
        title="t",
        description="d",
        content="Una pizza buona.",
        questions=[],
        vocab_annotations=[],
        vocab_annotated=False,
        drill_id=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


async def test_annotate_lesson_activities_sets_flags():
    payload = {
        "texts": [
            {
                "index": 0,
                "tokens": [{"surface": "pizza", "lemma": "pizza", "upos": "NOUN"}],
            }
        ]
    }
    act = _activity()
    skipped = _activity(
        vocab_annotated=True,
        vocab_annotations=[
            VocabAnnotation(surface_forms=["mangio"], lemma="mangiare", upos="VERB")
        ],
    )
    with patch(
        "maestro.vocab.annotate.llm_messages_create",
        new_callable=AsyncMock,
        return_value=_llm_response(payload),
    ) as mock_llm:
        await annotate_lesson_activities([act, skipped], language="it")

    assert act.vocab_annotated is True
    assert [a.lemma for a in act.vocab_annotations] == ["pizza"]
    # Pre-annotated activity untouched and not re-sent to the LLM
    assert [a.lemma for a in skipped.vocab_annotations] == ["mangiare"]
    prompt = mock_llm.call_args.kwargs["messages"][0]["content"]
    assert "mangio" not in prompt


async def test_annotate_lesson_activities_leaves_unannotated_on_failure():
    act = _activity()
    with patch(
        "maestro.vocab.annotate.llm_messages_create",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        await annotate_lesson_activities([act], language="it")
    assert act.vocab_annotated is False
    assert act.vocab_annotations == []
