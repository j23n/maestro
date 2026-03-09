"""Integration tests for learning/analyzer.py and learning/scorer.py with mocked LLM."""

import json
import pytest
from unittest.mock import MagicMock

import maestro.learning.analyzer as analyzer_module
import maestro.learning.scorer as scorer_module
from maestro import taxonomy
from maestro.models import ExerciseType


def _make_llm_response(text: str) -> MagicMock:
    """Build a fake Anthropic messages.create() return value."""
    content = MagicMock()
    content.text = text
    response = MagicMock()
    response.content = [content]
    response.model = "claude-sonnet-4-6"
    response.usage = MagicMock(input_tokens=100, output_tokens=200)
    return response


def _seed_cache(gp_codes=("GP_001", "GP_002"), cf_codes=("CF_001",), level="B2"):
    """Populate taxonomy cache (avoids DB hit)."""
    taxonomy.seed(
        gps=[
            MagicMock(code=c, cefr_level=level, label=c, description=c)
            for c in gp_codes
        ],
        cfs=[
            MagicMock(code=c, cefr_level=level, label=c, description=c)
            for c in cf_codes
        ],
    )


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset analyzer state between tests."""
    yield
    taxonomy.invalidate()


@pytest.mark.integration
async def test_short_message_skipped(db, mock_analyzer_client):
    """Messages under 3 words must be skipped without LLM call."""
    _seed_cache()
    result = await analyzer_module.analyze_message("Ciao")
    assert result is None
    mock_analyzer_client.messages.create.assert_not_called()


@pytest.mark.integration
async def test_valid_response_parsed(db, mock_analyzer_client):
    """Valid LLM JSON is parsed into a LearningEvent with correct fields."""
    _seed_cache()
    payload = {
        "grammar_correct": ["GP_001"],
        "grammar_errors": [],
        "functions_performed": ["CF_001"],
        "themes": ["family"],
    }
    mock_analyzer_client.messages.create.return_value = _make_llm_response(
        json.dumps(payload)
    )

    result = await analyzer_module.analyze_message("Ho una sorella che studia medicina")
    assert result is not None
    assert result.grammar_correct == ["GP_001"]
    assert result.grammar_errors == []
    assert result.functions_performed == ["CF_001"]
    assert result.themes == ["family"]


@pytest.mark.integration
async def test_unknown_codes_filtered(db, mock_analyzer_client):
    """Unknown grammar/CF codes returned by LLM are filtered out."""
    _seed_cache()
    payload = {
        "grammar_correct": ["GP_001", "GP_UNKNOWN"],
        "grammar_errors": ["GP_ALSO_UNKNOWN"],
        "functions_performed": ["CF_001", "CF_FAKE"],
        "themes": [],
    }
    mock_analyzer_client.messages.create.return_value = _make_llm_response(
        json.dumps(payload)
    )

    result = await analyzer_module.analyze_message("Mia sorella studia all'università")
    assert result is not None
    assert "GP_UNKNOWN" not in result.grammar_correct
    assert "GP_ALSO_UNKNOWN" not in result.grammar_errors
    assert "CF_FAKE" not in result.functions_performed
    assert "GP_001" in result.grammar_correct
    assert "CF_001" in result.functions_performed


@pytest.mark.integration
async def test_llm_failure_returns_none(db, mock_analyzer_client):
    """When LLM raises an exception, analyze_message returns None."""
    _seed_cache()
    mock_analyzer_client.messages.create.side_effect = RuntimeError("API down")

    result = await analyzer_module.analyze_message("Mia sorella studia all'università")
    assert result is None


@pytest.mark.integration
async def test_unparseable_response_returns_none(db, mock_analyzer_client):
    """Unparseable LLM response returns None."""
    _seed_cache()
    mock_analyzer_client.messages.create.return_value = _make_llm_response(
        "not json at all"
    )

    result = await analyzer_module.analyze_message("Mia sorella studia all'università")
    assert result is None


@pytest.mark.integration
async def test_feedback_fill_blank_success(mock_scorer_client):
    """feedback_fill_blank returns dict with expected keys on success."""
    _seed_cache()
    mock_scorer_client.messages.create.return_value = _make_llm_response(
        "Il verbo 'andare' richiede l'ausiliare 'essere'."
    )

    result = await scorer_module.feedback_fill_blank(
        drill_prompt="Ieri ___ (andare) al mercato.",
        correct_answer="sono andato",
        student_answer="ho andato",
        grammar_point_code="GP_001",
    )
    assert isinstance(result, dict)
    assert "wrong" in result
    assert "correct" in result
    assert "explanation" in result
    assert result["wrong"] == "ho andato"
    assert result["correct"] == "sono andato"


@pytest.mark.integration
async def test_feedback_fill_blank_failure(mock_scorer_client):
    """feedback_fill_blank returns empty string on LLM error."""
    _seed_cache()
    mock_scorer_client.messages.create.side_effect = RuntimeError("timeout")

    result = await scorer_module.feedback_fill_blank(
        drill_prompt="Ieri ___ al mercato.",
        correct_answer="sono andato",
        student_answer="ho andato",
        grammar_point_code="GP_001",
    )
    assert result == ""


@pytest.mark.integration
async def test_evaluate_error_correction_correct(mock_scorer_client):
    """evaluate_error_correction returns (True, feedback_dict) for a correct answer."""
    _seed_cache()
    mock_scorer_client.messages.create.return_value = _make_llm_response(
        '{"correct": true, "explanation": "Hai corretto l\'errore."}'
    )

    is_correct, feedback = await scorer_module.evaluate_error_correction(
        erroneous="Ho andato a scuola.",
        reference="Sono andato a scuola.",
        student="Sono andato a scuola.",
    )
    assert is_correct is True
    assert isinstance(feedback, dict)
    assert feedback["correct"] == "Sono andato a scuola."


@pytest.mark.integration
async def test_evaluate_error_correction_incorrect(mock_scorer_client):
    """evaluate_error_correction returns (False, feedback_dict) for a wrong answer."""
    _seed_cache()
    mock_scorer_client.messages.create.return_value = _make_llm_response(
        '{"correct": false, "explanation": "Hai usato l\'ausiliare sbagliato."}'
    )

    is_correct, feedback = await scorer_module.evaluate_error_correction(
        erroneous="Ho andato a scuola.",
        reference="Sono andato a scuola.",
        student="Ho andato a scuola.",
    )
    assert is_correct is False


@pytest.mark.integration
async def test_score_multi_item_drill_success(mock_scorer_client):
    """score_multi_item_drill returns a list of per-item dicts."""
    _seed_cache()
    items = [
        MagicMock(prompt="Ieri ___ al mercato.", correct_answer="sono andato"),
        MagicMock(prompt="Ieri ___ la pizza.", correct_answer="ho mangiato"),
    ]
    payload = [
        {
            "objective_correct": True,
            "objective_note": "",
            "grammar_errors": [],
            "tips": [],
        },
        {
            "objective_correct": False,
            "objective_note": "Sbagliato.",
            "grammar_errors": [],
            "tips": [],
        },
    ]
    mock_scorer_client.messages.create.return_value = _make_llm_response(
        json.dumps(payload)
    )

    result = await scorer_module.score_multi_item_drill(
        exercise_type=ExerciseType.FILL_BLANK,
        grammar_point_code="GP_001",
        items=items,
        student_answers=["sono andato", "ho mangiato"],
    )
    assert len(result) == 2
    assert result[0]["objective_correct"] is True
    assert result[1]["objective_correct"] is False


@pytest.mark.integration
async def test_score_multi_item_drill_fallback_on_failure(mock_scorer_client):
    """score_multi_item_drill returns all-incorrect fallback on LLM error."""
    _seed_cache()
    items = [MagicMock(prompt="Test.", correct_answer="answer")]
    mock_scorer_client.messages.create.side_effect = RuntimeError("error")

    result = await scorer_module.score_multi_item_drill(
        exercise_type=ExerciseType.FILL_BLANK,
        grammar_point_code="GP_001",
        items=items,
        student_answers=["wrong"],
    )
    assert len(result) == 1
    assert result[0]["objective_correct"] is False


@pytest.mark.integration
async def test_generate_writing_feedback_success(mock_scorer_client):
    """generate_writing_feedback returns dict with expected keys."""
    _seed_cache()
    payload = {
        "objective_correct": True,
        "objective_note": "",
        "grammar_errors": [],
        "tips": [],
    }
    mock_scorer_client.messages.create.return_value = _make_llm_response(
        json.dumps(payload)
    )

    result = await scorer_module.generate_writing_feedback(
        prompt="Descrivi la tua famiglia.",
        student_text="Ho una sorella e due fratelli.",
        cefr_level="A1",
    )
    assert isinstance(result, dict)
    assert "objective_correct" in result
    assert result["objective_correct"] is True
