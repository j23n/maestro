"""Unit tests for the weighted mastery computation."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from maestro.learning.mastery import (
    DECAY_BASE,
    EVIDENCE_WEIGHTS,
    MASTERY_THRESHOLD,
    compute_gp_mastery,
    is_mastered,
    mastery_label,
)


def _make_event(
    grammar_correct=None,
    grammar_errors=None,
    evidence_type="targeted",
    days_ago=0,
):
    """Create a mock LearningEvent-like object."""
    from types import SimpleNamespace

    created = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return SimpleNamespace(
        grammar_correct=grammar_correct or [],
        grammar_errors=grammar_errors or [],
        evidence_type=evidence_type,
        created_at=created,
    )


@pytest.fixture
def mock_find(request):
    """Patch LearningEvent.find to return controlled events."""
    from unittest.mock import MagicMock as _MagicMock

    class _MockQuery:
        def __init__(self, events):
            self._events = events

        def sort(self, _field):
            return self

        def limit(self, _n):
            return self

        async def to_list(self):
            return self._events

    _patcher = None

    def _setup(events):
        nonlocal _patcher
        mock = _MagicMock()
        mock.return_value = _MockQuery(events)
        _patcher = patch("maestro.learning.mastery.LearningEvent.find", mock)
        _patcher.start()

    def _cleanup():
        if _patcher is not None:
            _patcher.stop()

    request.addfinalizer(_cleanup)
    return _setup


@pytest.mark.asyncio
async def test_no_events_returns_zero(mock_find):
    mock_find([])
    score = await compute_gp_mastery("student1", "GP_001")
    assert score == 0.0


@pytest.mark.asyncio
async def test_all_correct_high_score(mock_find):
    events = [
        _make_event(grammar_correct=["GP_001"], evidence_type="targeted", days_ago=i)
        for i in range(5)
    ]
    mock_find(events)
    score = await compute_gp_mastery("student1", "GP_001")
    assert score > 0.9
    assert is_mastered(score)


@pytest.mark.asyncio
async def test_all_errors_negative_score(mock_find):
    events = [
        _make_event(grammar_errors=["GP_001"], evidence_type="targeted", days_ago=i)
        for i in range(5)
    ]
    mock_find(events)
    score = await compute_gp_mastery("student1", "GP_001")
    assert score < 0
    assert not is_mastered(score)


@pytest.mark.asyncio
async def test_mixed_outcomes(mock_find):
    events = [
        _make_event(grammar_correct=["GP_001"], evidence_type="targeted", days_ago=0),
        _make_event(grammar_correct=["GP_001"], evidence_type="targeted", days_ago=1),
        _make_event(grammar_correct=["GP_001"], evidence_type="targeted", days_ago=2),
        _make_event(grammar_errors=["GP_001"], evidence_type="targeted", days_ago=3),
        _make_event(grammar_errors=["GP_001"], evidence_type="targeted", days_ago=4),
    ]
    mock_find(events)
    score = await compute_gp_mastery("student1", "GP_001")
    # 3 correct, 2 errors — score should be positive but below mastery
    assert 0 < score < MASTERY_THRESHOLD


@pytest.mark.asyncio
async def test_recency_decay(mock_find):
    # Recent correct events should outweigh old errors
    events = [
        _make_event(grammar_correct=["GP_001"], evidence_type="targeted", days_ago=0),
        _make_event(grammar_correct=["GP_001"], evidence_type="targeted", days_ago=1),
        _make_event(grammar_correct=["GP_001"], evidence_type="targeted", days_ago=2),
        _make_event(grammar_correct=["GP_001"], evidence_type="targeted", days_ago=3),
        _make_event(grammar_errors=["GP_001"], evidence_type="targeted", days_ago=60),
        _make_event(grammar_errors=["GP_001"], evidence_type="targeted", days_ago=61),
    ]
    mock_find(events)
    score = await compute_gp_mastery("student1", "GP_001")
    # Old errors have ~5% weight (0.95^60 ≈ 0.046), should barely affect score
    assert score > 0.8


@pytest.mark.asyncio
async def test_productive_evidence_weighs_more(mock_find):
    # Productive correct = weight 1.5, targeted error = weight 1.0
    # Need enough events to cross MIN_WEIGHTED_DENOM (3.0)
    events = [
        _make_event(grammar_correct=["GP_001"], evidence_type="productive", days_ago=0),
        _make_event(grammar_correct=["GP_001"], evidence_type="productive", days_ago=1),
        _make_event(grammar_errors=["GP_001"], evidence_type="targeted", days_ago=0),
    ]
    mock_find(events)
    score = await compute_gp_mastery("student1", "GP_001")
    # 2 productive correct (weight 1.5 each) + 1 targeted error (weight 1.0)
    # numerator ≈ 1.5 + 1.5*0.95 - 1.0 ≈ 1.925
    # denominator ≈ 1.5 + 1.5*0.95 + 1.0 ≈ 3.925
    # score ≈ 0.49
    assert 0 < score < 0.7


@pytest.mark.asyncio
async def test_below_min_denominator_returns_zero(mock_find):
    # Single event with weight 1.0 < MIN_WEIGHTED_DENOM (3.0)
    events = [
        _make_event(grammar_correct=["GP_001"], evidence_type="targeted", days_ago=0),
    ]
    mock_find(events)
    score = await compute_gp_mastery("student1", "GP_001")
    assert score == 0.0


@pytest.mark.asyncio
async def test_at_min_denominator(mock_find):
    # 4 targeted events at weight 1.0 each → denominator > MIN_WEIGHTED_DENOM (3.0)
    events = [
        _make_event(grammar_correct=["GP_001"], evidence_type="targeted", days_ago=0),
        _make_event(grammar_correct=["GP_001"], evidence_type="targeted", days_ago=0),
        _make_event(grammar_correct=["GP_001"], evidence_type="targeted", days_ago=0),
        _make_event(grammar_correct=["GP_001"], evidence_type="targeted", days_ago=1),
    ]
    mock_find(events)
    score = await compute_gp_mastery("student1", "GP_001")
    assert score > 0.9  # All correct


def test_is_mastered_threshold():
    assert is_mastered(0.8) is True
    assert is_mastered(0.9) is True
    assert is_mastered(0.79) is False
    assert is_mastered(0.0) is False
    assert is_mastered(-0.5) is False


@pytest.mark.parametrize(
    "score,expected",
    [
        (None, "new"),
        (-1.0, "weak"),
        (-0.3, "weak"),
        (0.0, "weak"),
        (0.49, "weak"),
        (0.5, "developing"),
        (0.79, "developing"),
        (0.8, "consolidated"),
        (1.0, "consolidated"),
    ],
)
def test_mastery_label(score, expected):
    assert mastery_label(score) == expected


def test_evidence_weights_defined():
    assert EVIDENCE_WEIGHTS["targeted"] == 1.0
    assert EVIDENCE_WEIGHTS["productive"] == 1.5
    assert EVIDENCE_WEIGHTS["receptive"] == 0.5


def test_decay_base():
    # 30 days → ~21% weight
    weight_30 = DECAY_BASE**30
    assert 0.2 < weight_30 < 0.25
