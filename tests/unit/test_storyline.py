"""Unit tests for storyline evolution. LLM calls are mocked; no DB access."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from maestro.lessons.storyline import (
    _clean_storyline_text,
    _render_persona_block,
    _render_recent_lessons_block,
    evolve_storyline,
)
from maestro.models import StudentPersona


@pytest.mark.unit
def test_clean_storyline_strips_markdown_and_collapses_whitespace():
    raw = "# Heading\n\n**Bold** text. *italic* here.  Extra   spaces."
    cleaned = _clean_storyline_text(raw)
    assert cleaned == "Heading Bold text. italic here. Extra spaces."


@pytest.mark.unit
def test_clean_storyline_strips_surrounding_quotes_and_fences():
    assert _clean_storyline_text('"quoted"') == "quoted"
    assert _clean_storyline_text("```\nblock\n```") == "block"


@pytest.mark.unit
def test_clean_storyline_trims_to_max_chars():
    raw = "word " * 400  # ~2000 chars
    cleaned = _clean_storyline_text(raw)
    assert len(cleaned) <= 800 + 1  # +1 for ellipsis char
    assert cleaned.endswith("…")


@pytest.mark.unit
def test_render_persona_block_none_and_empty():
    assert "(none recorded)" in _render_persona_block(None)
    assert "(none recorded)" in _render_persona_block(StudentPersona())


@pytest.mark.unit
def test_render_persona_block_populated():
    p = StudentPersona(background="retiree", interests="cooking", goal="travel")
    out = _render_persona_block(p)
    assert "retiree" in out
    assert "cooking" in out
    assert "travel" in out


@pytest.mark.unit
def test_render_recent_lessons_block_empty_and_chronological():
    assert "no completed lessons" in _render_recent_lessons_block([])
    l1 = SimpleNamespace(
        topic_title="First", topic_description="d1", scenario_slug="s1", archetype="a1"
    )
    l2 = SimpleNamespace(
        topic_title="Second", topic_description="d2", scenario_slug="s2", archetype="a2"
    )
    # Input is newest-first (as DB returns); render should reverse to oldest-first
    out = _render_recent_lessons_block([l2, l1])
    assert out.index("First") < out.index("Second")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evolve_storyline_short_circuits_on_empty_inputs():
    # Empty old + empty recent ⇒ no LLM call, returns "".
    out = await evolve_storyline(
        old_storyline="",
        persona=StudentPersona(),
        recent_lessons=[],
        language="it",
        student_id=None,
        profile_id=None,
    )
    assert out == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evolve_storyline_returns_cleaned_text(monkeypatch):
    from maestro.lessons import storyline as storyline_mod

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text="  A fresh story.  ")]
    mock_llm = AsyncMock(return_value=fake_response)
    monkeypatch.setattr(storyline_mod, "llm_messages_create", mock_llm)

    recent = [
        SimpleNamespace(
            topic_title="At the bar",
            topic_description="Ordering coffee",
            scenario_slug="al-bar",
            archetype="consolidation",
        )
    ]
    out = await evolve_storyline(
        old_storyline="Prior.",
        persona=StudentPersona(interests="coffee"),
        recent_lessons=recent,
        language="it",
        student_id=None,
        profile_id=None,
    )
    assert out == "A fresh story."
    assert mock_llm.await_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evolve_storyline_returns_old_on_llm_failure(monkeypatch):
    from maestro.lessons import storyline as storyline_mod

    async def boom(*args, **kwargs):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(storyline_mod, "llm_messages_create", boom)

    old = "Prior storyline."
    recent = [
        SimpleNamespace(
            topic_title="T",
            topic_description="D",
            scenario_slug="s",
            archetype="a",
        )
    ]
    out = await evolve_storyline(
        old_storyline=old,
        persona=StudentPersona(),
        recent_lessons=recent,
        language="it",
        student_id=None,
        profile_id=None,
    )
    assert out == old


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evolve_storyline_returns_old_on_empty_llm_text(monkeypatch):
    from maestro.lessons import storyline as storyline_mod

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text="   \n  ")]
    monkeypatch.setattr(
        storyline_mod, "llm_messages_create", AsyncMock(return_value=fake_response)
    )

    out = await evolve_storyline(
        old_storyline="Keep me.",
        persona=StudentPersona(),
        recent_lessons=[
            SimpleNamespace(
                topic_title="T", topic_description="D", scenario_slug="s", archetype="a"
            )
        ],
        language="it",
        student_id=None,
        profile_id=None,
    )
    assert out == "Keep me."


@pytest.mark.unit
def test_language_progress_storyline_defaults():
    from maestro.models import LanguageProgress

    lp = LanguageProgress()
    assert lp.storyline == ""
    assert lp.storyline_lessons_since_evolve == 0
    assert lp.storyline_updated_at is None
