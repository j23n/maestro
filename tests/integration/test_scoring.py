"""Integration tests for drills/scoring.py with mocked LLM."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from maestro.models import GeneratedDrill, DrillItem, ExerciseType
from maestro import taxonomy


def _make_drill(exercise_type: str, gp_code: str, items: list = None) -> MagicMock:
    drill = MagicMock(spec=GeneratedDrill)
    drill.exercise_type = exercise_type
    drill.grammar_point_code = gp_code
    drill.items = items or []
    drill.prompt = "Test prompt"
    drill.chunk_ref = None
    return drill


@pytest.mark.integration
async def test_unknown_exercise_type_returns_none(db):
    """Drills with unknown exercise_type return (None, None, '', [])."""
    from maestro.drills.scoring import score_attempt

    drill = _make_drill("unknown_type", "GP_001")
    drill.items = []

    correct, event, feedback, refs = await score_attempt(drill, "some answer")

    assert correct is None
    assert event is None
    assert feedback == ""
    assert refs == []


@pytest.mark.integration
async def test_fill_blank_passing(db, mocker):
    """fill_blank with ≥70% correct items passes and creates event with grammar_correct."""
    taxonomy.seed(
        gps=[MagicMock(code="GP_001", label="Passato Prossimo", cefr_level="A1")]
    )

    items = [
        DrillItem(prompt=f"Sentence {i} ___", correct_answer="answer") for i in range(3)
    ]
    drill = _make_drill(ExerciseType.FILL_BLANK, "GP_001", items)

    # 3/3 correct
    llm_results = [
        {
            "objective_correct": True,
            "objective_note": "",
            "grammar_errors": [],
            "tips": [],
        }
        for _ in range(3)
    ]
    mocker.patch(
        "maestro.drills.scoring.score_multi_item_drill",
        new_callable=AsyncMock,
        return_value=llm_results,
    )

    from maestro.drills.scoring import score_attempt

    correct, event, feedback, refs = await score_attempt(drill, ["answer"] * 3)

    assert correct is True
    assert event is not None
    assert "GP_001" in event.grammar_correct
    assert "GP_001" not in event.grammar_errors


@pytest.mark.integration
async def test_fill_blank_failing(db, mocker):
    """fill_blank with <70% correct items fails and creates event with grammar_errors."""
    taxonomy.seed(
        gps=[MagicMock(code="GP_001", label="Passato Prossimo", cefr_level="A1")]
    )

    items = [
        DrillItem(prompt=f"Sentence {i} ___", correct_answer="answer") for i in range(3)
    ]
    drill = _make_drill(ExerciseType.FILL_BLANK, "GP_001", items)

    # 1/3 correct (33% < 70% threshold)
    llm_results = [
        {
            "objective_correct": True,
            "objective_note": "",
            "grammar_errors": [],
            "tips": [],
        },
        {
            "objective_correct": False,
            "objective_note": "Wrong.",
            "grammar_errors": [],
            "tips": [],
        },
        {
            "objective_correct": False,
            "objective_note": "Wrong.",
            "grammar_errors": [],
            "tips": [],
        },
    ]
    mocker.patch(
        "maestro.drills.scoring.score_multi_item_drill",
        new_callable=AsyncMock,
        return_value=llm_results,
    )

    from maestro.drills.scoring import score_attempt

    correct, event, feedback, refs = await score_attempt(drill, ["wrong"] * 3)

    assert correct is False
    assert event is not None
    assert "GP_001" in event.grammar_errors
    assert "GP_001" not in event.grammar_correct


@pytest.mark.integration
async def test_pass_threshold_exactly_at_70(db, mocker):
    """2/3 items (67%) is below the 0.7 threshold → fail; 3/3 (100%) → pass."""
    taxonomy.seed(gps=[MagicMock(code="GP_001", label="Test GP", cefr_level="A1")])

    items = [DrillItem(prompt=f"Q{i} ___", correct_answer="x") for i in range(3)]
    drill = _make_drill(ExerciseType.FILL_BLANK, "GP_001", items)

    two_of_three = [
        {
            "objective_correct": True,
            "objective_note": "",
            "grammar_errors": [],
            "tips": [],
        },
        {
            "objective_correct": True,
            "objective_note": "",
            "grammar_errors": [],
            "tips": [],
        },
        {
            "objective_correct": False,
            "objective_note": "Wrong.",
            "grammar_errors": [],
            "tips": [],
        },
    ]
    mocker.patch(
        "maestro.drills.scoring.score_multi_item_drill",
        new_callable=AsyncMock,
        return_value=two_of_three,
    )

    from maestro.drills.scoring import score_attempt

    correct, event, feedback, refs = await score_attempt(drill, ["x"] * 3)
    # 2/3 = 0.667 < 0.7
    assert correct is False


@pytest.mark.integration
async def test_free_form_correct(db, mocker):
    """free_form with objective_correct=True creates event with grammar_correct."""
    taxonomy.seed(gps=[MagicMock(code="GP_001", label="Test GP", cefr_level="A1")])

    drill = _make_drill(ExerciseType.FREE_FORM, "GP_001", items=[])
    mocker.patch(
        "maestro.drills.scoring.score_free_form_drill",
        new_callable=AsyncMock,
        return_value={
            "objective_correct": True,
            "objective_note": "",
            "grammar_errors": [],
            "tips": [],
        },
    )

    from maestro.drills.scoring import score_attempt

    correct, event, feedback, refs = await score_attempt(
        drill, "Una risposta lunga e completa."
    )

    assert correct is True
    assert "GP_001" in event.grammar_correct
    assert refs == []


@pytest.mark.integration
async def test_free_form_incorrect(db, mocker):
    """free_form with objective_correct=False creates event with grammar_errors."""
    taxonomy.seed(gps=[MagicMock(code="GP_001", label="Test GP", cefr_level="A1")])

    drill = _make_drill(ExerciseType.FREE_FORM, "GP_001", items=[])
    drill.chunk_ref = "test_chunk_ref"
    mocker.patch(
        "maestro.drills.scoring.score_free_form_drill",
        new_callable=AsyncMock,
        return_value={
            "objective_correct": False,
            "objective_note": "Risposta fuori tema.",
            "grammar_errors": [],
            "tips": [],
        },
    )
    chunk = MagicMock()
    chunk.content = "rule text"
    chunk.chunk_metadata = {"heading": "Rule heading"}
    chunk.ref = "test_chunk_ref"
    mocker.patch(
        "maestro.drills.scoring.GrammarChunk.find_one",
        new_callable=AsyncMock,
        return_value=chunk,
    )

    from maestro.drills.scoring import score_attempt

    correct, event, feedback, refs = await score_attempt(drill, "")

    assert correct is False
    assert "GP_001" in event.grammar_errors
    assert len(refs) > 0
