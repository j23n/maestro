"""Reference pages (grammar/CF detail) render popovers from stored annotations."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from maestro.models import (
    CommunicativeFunction,
    Explanation,
    GrammarPoint,
    VocabAnnotation,
)
from maestro.vocab import cache as _vocab_cache

pytestmark = pytest.mark.integration


def _word(headword, pos):
    return SimpleNamespace(
        word=headword,
        part_of_speech=pos,
        syllabization="",
        ipa=None,
        entry_id=f"LM-{headword.upper()}",
        senses=[],
        id=f"fake-{headword}",
        audio_url=None,
        language="it",
    )


@pytest.fixture(autouse=True)
def seeded_cache():
    _vocab_cache.seed(
        words={"mangiare": [_word("mangiare", "v.tr.")]}, defs={}, language="it"
    )
    yield
    _vocab_cache.invalidate("it")


def test_grammar_detail_renders_annotation_popovers(test_app, db):
    async def _seed():
        await GrammarPoint(
            code="gp_test",
            label="Presente",
            cefr_level="A1",
            category="verbs",
            explanations={
                "en": Explanation(
                    title="Present tense",
                    explanation="Use it like <span lang='it'>io mangio</span>.",
                    language="en",
                )
            },
            vocab_annotations=[
                VocabAnnotation(surface_forms=["mangio"], lemma="mangiare", upos="VERB")
            ],
            language="it",
        ).insert()

    asyncio.get_event_loop().run_until_complete(_seed())

    response = test_app.get("/grammar/gp_test")
    assert response.status_code == 200
    assert 'data-word="mangiare"' in response.text


def test_cf_detail_renders_annotation_popovers(test_app, db):
    async def _seed():
        await CommunicativeFunction(
            code="cf_test",
            label="Ordinare",
            category="test",
            cefr_level="A1",
            patterns=["Vorrei mangiare qualcosa"],
            vocab_annotations=[
                VocabAnnotation(
                    surface_forms=["mangiare"], lemma="mangiare", upos="VERB"
                )
            ],
            language="it",
        ).insert()

    asyncio.get_event_loop().run_until_complete(_seed())

    response = test_app.get("/cf/cf_test")
    assert response.status_code == 200
    assert 'data-word="mangiare"' in response.text


def test_grammar_detail_without_annotations_renders_plain(test_app, db):
    async def _seed():
        await GrammarPoint(
            code="gp_plain",
            label="Articoli",
            cefr_level="A1",
            category="articles",
            explanations={
                "en": Explanation(
                    title="Articles",
                    explanation="Like <span lang='it'>io mangio</span>.",
                    language="en",
                )
            },
            language="it",
        ).insert()

    asyncio.get_event_loop().run_until_complete(_seed())

    response = test_app.get("/grammar/gp_plain")
    assert response.status_code == 200
    assert 'data-word="mangiare"' not in response.text
