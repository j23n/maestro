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
def test_clean_storyline_trims_whitespace_and_quotes():
    # We rely on the system prompt to forbid markdown — the cleaner just
    # trims surrounding whitespace and quote marks the model often adds.
    assert _clean_storyline_text("  hello world  ") == "hello world"
    assert _clean_storyline_text('"quoted"') == "quoted"
    assert _clean_storyline_text("“smart-quoted”") == "smart-quoted"


@pytest.mark.unit
def test_clean_storyline_caps_length():
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


# ---------------------------------------------------------------------------
# Per-lesson summarizer
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_collect_student_signals_picks_writing_and_speaking():
    from maestro.lessons.storyline import _collect_student_signals
    from maestro.models import ActivityStatus, ActivityType

    lesson = SimpleNamespace(
        lesson_context="I'm planning a move to Bologna",
        activities=[
            SimpleNamespace(
                type=ActivityType.WRITING,
                status=ActivityStatus.COMPLETED,
                content="Describe your weekend",
                result={"student_answer": "I walked my dog Luna in the park."},
            ),
            SimpleNamespace(
                type=ActivityType.SPEAKING,
                status=ActivityStatus.COMPLETED,
                content="Order at the bar",
                result={"recognized_text": "Vorrei un caffè per favore"},
            ),
            # Skipped activity is ignored
            SimpleNamespace(
                type=ActivityType.WRITING,
                status=ActivityStatus.SKIPPED,
                content="ignored",
                result={"student_answer": "should not appear"},
            ),
            # Drill is ignored even when completed
            SimpleNamespace(
                type=ActivityType.DRILL,
                status=ActivityStatus.COMPLETED,
                content="x",
                result={"correct": 5},
            ),
        ],
    )
    signals = _collect_student_signals(lesson)
    labels = [label for label, _ in signals]
    texts = [text for _, text in signals]
    assert any("Student's note" in label for label in labels)
    assert any("Writing" in label for label in labels)
    assert any("Speaking" in label for label in labels)
    assert "I walked my dog Luna in the park." in texts
    assert "Vorrei un caffè per favore" in texts
    assert all("should not appear" not in t for t in texts)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_lesson_short_circuits_without_signals():
    from maestro.lessons.storyline import summarize_lesson

    lesson = SimpleNamespace(
        lesson_context=None,
        activities=[],
        topic_title="Al bar",
        topic_description="Coffee",
        scenario_slug="al-bar",
        archetype="introduction",
        language="it",
        id=None,
        student_id=None,
    )
    out = await summarize_lesson(lesson)
    assert out == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_lesson_returns_cleaned_text(monkeypatch):
    from maestro.lessons import storyline as storyline_mod
    from maestro.models import ActivityStatus, ActivityType

    fake_response = MagicMock()
    fake_response.content = [
        MagicMock(text='"Walked Luna and ordered an espresso at the bar."  ')
    ]
    monkeypatch.setattr(
        storyline_mod, "llm_messages_create", AsyncMock(return_value=fake_response)
    )

    lesson = SimpleNamespace(
        lesson_context="Day off in Bologna",
        activities=[
            SimpleNamespace(
                type=ActivityType.WRITING,
                status=ActivityStatus.COMPLETED,
                content="What did you do?",
                result={"student_answer": "I walked my dog."},
            )
        ],
        topic_title="Al bar",
        topic_description=None,
        scenario_slug="al-bar",
        archetype="application",
        language="it",
        id=None,
        student_id=None,
    )
    out = await storyline_mod.summarize_lesson(lesson)
    assert out == "Walked Luna and ordered an espresso at the bar."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_lesson_returns_empty_on_llm_failure(monkeypatch):
    from maestro.lessons import storyline as storyline_mod
    from maestro.models import ActivityStatus, ActivityType

    async def boom(*a, **kw):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(storyline_mod, "llm_messages_create", boom)

    lesson = SimpleNamespace(
        lesson_context="X",
        activities=[
            SimpleNamespace(
                type=ActivityType.WRITING,
                status=ActivityStatus.COMPLETED,
                content="prompt",
                result={"student_answer": "answer"},
            )
        ],
        topic_title="t",
        topic_description=None,
        scenario_slug=None,
        archetype=None,
        language="it",
        id=None,
        student_id=None,
    )
    out = await storyline_mod.summarize_lesson(lesson)
    assert out == ""


@pytest.mark.unit
def test_render_recent_lessons_prefers_summary_when_present():
    from maestro.lessons.storyline import _render_recent_lessons_block

    with_summary = SimpleNamespace(
        topic_title="At the bar",
        topic_description="Coffee",
        scenario_slug="al-bar",
        archetype="introduction",
        summary="Walked Luna in the park before grabbing an espresso.",
    )
    without_summary = SimpleNamespace(
        topic_title="At the station",
        topic_description="Buying tickets",
        scenario_slug="in-stazione",
        archetype="consolidation",
        summary=None,
    )
    out = _render_recent_lessons_block([with_summary, without_summary])
    assert "Walked Luna" in out
    assert "At the station" in out  # fallback path still works
    # Summary line should NOT include the title duplicate
    summary_line = [line for line in out.splitlines() if "Walked Luna" in line][0]
    assert "At the bar" not in summary_line


@pytest.mark.unit
def test_section_recent_lessons_prefers_summary():
    from maestro.lessons.sections import section_recent_lessons

    with_summary = SimpleNamespace(
        topic_title="At the bar",
        topic_description="Coffee",
        scenario_slug="al-bar",
        archetype="introduction",
        summary="Walked Luna in the park before grabbing an espresso.",
    )
    out = section_recent_lessons([with_summary])
    assert "Walked Luna" in out
    assert "<recent_lessons>" in out
    summary_line = [line for line in out.splitlines() if "Walked Luna" in line][0]
    assert "At the bar" not in summary_line
