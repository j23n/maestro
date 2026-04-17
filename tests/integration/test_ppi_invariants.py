"""Regression guards: PPI must not appear in persisted documents.

See issue #19. These tests assert that the Beanie models for lessons,
learning events, and drill attempts do not re-introduce fields that
store student-generated content or raw LLM output.
"""

import importlib

import pytest

from maestro.models import DrillAttempt, LearningEvent, Lesson


_BANNED_TOP_LEVEL = {
    DrillAttempt: {"student_answer"},
    LearningEvent: {"student_text", "feedback"},
    Lesson: {"feedback_summary"},
}

_BANNED_ACTIVITY_RESULT_KEYS = {
    "student_answer",
    "student_answers",
    "recognized_text",
    "feedback",
    "item_scores",
    "word_assessments",
}


@pytest.mark.unit
@pytest.mark.parametrize("model,banned", list(_BANNED_TOP_LEVEL.items()))
def test_model_has_no_ppi_fields(model, banned):
    """Beanie model schemas must not declare any PPI fields."""
    fields = set(model.model_fields.keys())
    leaked = fields & banned
    assert not leaked, f"{model.__name__} declares PPI fields: {leaked}"


@pytest.mark.unit
def test_migration_0012_covers_expected_result_keys():
    """The 0012 migration key list must stay in sync with the banned set
    so newly added PPI keys don't silently slip past cleanup."""
    module = importlib.import_module("maestro.migrations.0012_remove_ppi")
    assert set(module._ACTIVITY_RESULT_PPI_KEYS) == _BANNED_ACTIVITY_RESULT_KEYS
