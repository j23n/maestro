"""Unit tests for inject_discovered_reviews — mid/end-of-lesson vocab review."""

import pytest

from maestro.models import LessonActivity, ActivityType


@pytest.mark.unit
def test_inject_adds_two_discovered_reviews():
    """Should add a mid-lesson and end-of-lesson discovered vocab review."""
    activities = [
        LessonActivity(type=ActivityType.GRAMMAR, title="G1", description=""),
        LessonActivity(type=ActivityType.DRILL, title="D1", description=""),
        LessonActivity(type=ActivityType.READING, title="R1", description=""),
        LessonActivity(type=ActivityType.LISTENING, title="L1", description=""),
        LessonActivity(type=ActivityType.SPEAKING, title="S1", description=""),
    ]

    from maestro.lessons.lifecycle import inject_discovered_reviews

    inject_discovered_reviews(activities)

    discovered = [a for a in activities if a.review_scope == "discovered"]
    assert len(discovered) == 2

    # Mid-lesson: inserted right after the first reading
    mid = activities[3]
    assert mid.review_scope == "discovered"
    assert mid.type == ActivityType.VOCAB_REVIEW
    assert mid.card_ids == []

    # End-of-lesson: always last
    end = activities[-1]
    assert end.review_scope == "discovered"
    assert end.type == ActivityType.VOCAB_REVIEW


@pytest.mark.unit
def test_inject_no_reading_or_listening():
    """Without reading/listening, only end-of-lesson review is added."""
    activities = [
        LessonActivity(type=ActivityType.GRAMMAR, title="G1", description=""),
        LessonActivity(type=ActivityType.DRILL, title="D1", description=""),
    ]

    from maestro.lessons.lifecycle import inject_discovered_reviews

    inject_discovered_reviews(activities)

    discovered = [a for a in activities if a.review_scope == "discovered"]
    assert len(discovered) == 1
    assert activities[-1].review_scope == "discovered"


@pytest.mark.unit
def test_inject_does_not_affect_existing_vocab_reviews():
    """Existing SRS vocab_review activities should keep review_scope=None."""
    activities = [
        LessonActivity(type=ActivityType.VOCAB_REVIEW, title="SRS", description=""),
        LessonActivity(type=ActivityType.GRAMMAR, title="G1", description=""),
        LessonActivity(type=ActivityType.READING, title="R1", description=""),
        LessonActivity(type=ActivityType.DRILL, title="D1", description=""),
    ]

    from maestro.lessons.lifecycle import inject_discovered_reviews

    inject_discovered_reviews(activities)

    srs = activities[0]
    assert srs.review_scope is None
    assert srs.title == "SRS"
