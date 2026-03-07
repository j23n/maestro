"""Integration tests for lezione/service.py helper functions."""
import pytest
from unittest.mock import MagicMock


@pytest.mark.integration
async def test_score_reading_activity_all_correct(mock_scorer_client, db):
    """All correct answers → overall_correct=True, correct_count matches."""
    from maestro.lezione.service import score_reading_activity

    mock_scorer_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text='[{"objective_correct": true, "objective_note": "Good", "grammar_errors": [], "tips": []}]')]
    )

    overall, feedback = await score_reading_activity(
        questions=["What color?"],
        correct_answers=["Red"],
        student_answers=["Red"],
    )
    assert overall is True
    assert feedback["correct_count"] == 1
    assert feedback["total"] == 1
    assert feedback["items"][0]["objective_correct"] is True


@pytest.mark.integration
async def test_score_reading_activity_below_threshold(mock_scorer_client, db):
    """Below 70% correct → overall_correct=False."""
    from maestro.lezione.service import score_reading_activity

    # 1 correct out of 3 = 33% < 70%
    mock_scorer_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text='[{"objective_correct": true, "objective_note": "", "grammar_errors": [], "tips": []}, {"objective_correct": false, "objective_note": "", "grammar_errors": [], "tips": []}, {"objective_correct": false, "objective_note": "", "grammar_errors": [], "tips": []}]')]
    )

    overall, feedback = await score_reading_activity(
        questions=["Q1", "Q2", "Q3"],
        correct_answers=["A1", "A2", "A3"],
        student_answers=["A1", "wrong", "wrong"],
    )
    assert overall is False
    assert feedback["correct_count"] == 1
    assert feedback["total"] == 3


@pytest.mark.integration
async def test_score_reading_activity_enriched_fields(mock_scorer_client, db):
    """Enriched feedback items contain prompt, correct_answer, and student_answer."""
    from maestro.lezione.service import score_reading_activity

    mock_scorer_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text='[{"objective_correct": false, "objective_note": "Wrong color", "grammar_errors": ["GP001"], "tips": ["Check colors"]}]')]
    )

    _, feedback = await score_reading_activity(
        questions=["What color is the sky?"],
        correct_answers=["Blue"],
        student_answers=["Green"],
    )
    item = feedback["items"][0]
    assert item["prompt"] == "What color is the sky?"
    assert item["correct_answer"] == "Blue"
    assert item["student_answer"] == "Green"
    assert item["objective_note"] == "Wrong color"
    assert "GP001" in item["grammar_errors"]
    assert "Check colors" in item["tips"]
