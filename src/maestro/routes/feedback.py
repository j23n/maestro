"""Feedback routes — LLM critique flagging."""

from __future__ import annotations

import json
import logging
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from maestro.auth import get_current_student
from maestro.models import (
    CallType,
    GeneratedDrill,
    GrammarPoint,
    LearningEvent,
    Lesson,
    LLMCritique,
    DrillAttempt,
    Student,
    VocabularyWord,
    VocabularyWordDefinition,
)
from maestro import prompts as _prompts
from maestro.utils import explanation_lang_for_level

logger = logging.getLogger(__name__)

router = APIRouter()


def _prompt_version_for_call_type(call_type: CallType) -> str:
    """Return the prompt version string for a given call type."""
    if call_type in (CallType.ANALYZER,):
        return _prompts.analyzer.version
    if call_type in (CallType.SCORER_SINGLE, CallType.SCORER_MULTI):
        return _prompts.scorer.version
    if call_type in (CallType.LESSON_FEEDBACK, CallType.LESSON_PLAN):
        return _prompts.planner.version
    if call_type in (CallType.LESSON_ANALYZER_CF1, CallType.LESSON_ANALYZER_CF2):
        return _prompts.lesson_analyzer.version
    if call_type == CallType.VOCAB_DEFINITION:
        return _prompts.vocab.version
    if call_type == CallType.GRAMMAR_EXPLANATION:
        return _prompts.grammar.version
    return "unknown"


async def _reconstruct_analyzer(refs: dict) -> tuple[dict, dict]:
    """Reconstruct input/output for ANALYZER call type."""
    lesson_id = PydanticObjectId(refs["lesson_id"])
    activity_index = int(refs["activity_index"])
    event = await LearningEvent.find_one(
        {"lesson_id": lesson_id, "activity_index": activity_index}
    )
    if event is None:
        return {"error": "LearningEvent not found"}, {}
    input_snapshot = {"student_text": event.student_text}
    actual_output = {
        "grammar_correct": event.grammar_correct,
        "grammar_errors": event.grammar_errors,
        "functions_performed": event.functions_performed,
        "themes": event.themes,
    }
    return input_snapshot, actual_output


async def _reconstruct_scorer_multi(refs: dict) -> tuple[dict, dict]:
    """Reconstruct input/output for SCORER_MULTI call type."""
    lesson_id = PydanticObjectId(refs["lesson_id"])
    activity_index = int(refs["activity_index"])
    item_index = int(refs["item_index"])

    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        return {"error": "Lesson not found"}, {}
    if activity_index >= len(lesson.activities):
        return {"error": "activity_index out of range"}, {}
    activity = lesson.activities[activity_index]

    if activity.drill_id is None:
        return {"error": "No drill on this activity"}, {}
    drill = await GeneratedDrill.get(activity.drill_id)
    if drill is None:
        return {"error": "GeneratedDrill not found"}, {}

    # Most recent attempt for this drill + student
    attempt = await DrillAttempt.find_one(
        {"generated_drill.$id": drill.id, "student_id": lesson.student_id},
        sort=[("attempted_at", -1)],
    )
    if attempt is None:
        return {"error": "DrillAttempt not found"}, {}

    try:
        answers = json.loads(attempt.student_answer)
        if not isinstance(answers, list):
            answers = [attempt.student_answer]
    except (json.JSONDecodeError, TypeError):
        answers = [attempt.student_answer]

    if item_index >= len(drill.items):
        return {"error": "item_index out of range"}, {}

    input_snapshot = {
        "exercise_type": drill.exercise_type,
        "grammar_point_code": drill.grammar_point_code,
        "prompt": drill.items[item_index].prompt,
        "correct_answer": drill.items[item_index].correct_answer,
        "student_answer": answers[item_index] if item_index < len(answers) else "",
    }
    item_scores = (
        (activity.result or {}).get("item_scores", []) if activity.result else []
    )
    actual_output = item_scores[item_index] if item_index < len(item_scores) else {}
    return input_snapshot, actual_output


async def _reconstruct_scorer_single(refs: dict) -> tuple[dict, dict]:
    """Reconstruct input/output for SCORER_SINGLE call type."""
    lesson_id = PydanticObjectId(refs["lesson_id"])
    activity_index = int(refs["activity_index"])

    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        return {"error": "Lesson not found"}, {}
    if activity_index >= len(lesson.activities):
        return {"error": "activity_index out of range"}, {}
    activity = lesson.activities[activity_index]

    if activity.drill_id is None:
        return {"error": "No drill on this activity"}, {}
    drill = await GeneratedDrill.get(activity.drill_id)
    if drill is None:
        return {"error": "GeneratedDrill not found"}, {}

    attempt = await DrillAttempt.find_one(
        {"generated_drill.$id": drill.id, "student_id": lesson.student_id},
        sort=[("attempted_at", -1)],
    )
    if attempt is None:
        return {"error": "DrillAttempt not found"}, {}

    input_snapshot = {
        "exercise_type": drill.exercise_type,
        "prompt": drill.prompt,
        "correct_answer": drill.correct_answer,
        "student_answer": attempt.student_answer,
    }
    actual_output = (
        (activity.result or {}).get("score_detail", {}) if activity.result else {}
    )
    return input_snapshot, actual_output


async def _reconstruct_lesson_feedback(refs: dict) -> tuple[dict, dict]:
    """Reconstruct input/output for LESSON_FEEDBACK call type."""
    lesson_id = PydanticObjectId(refs["lesson_id"])
    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        return {"error": "Lesson not found"}, {}
    events = await LearningEvent.find({"lesson_id": lesson_id}).to_list()
    input_snapshot = {
        "topic_title": lesson.topic_title or "",
        "topic_description": lesson.topic_description or "",
        "student_responses": [e.student_text for e in events if e.student_text],
    }
    actual_output = {"feedback_summary": lesson.feedback_summary}
    return input_snapshot, actual_output


async def _reconstruct_vocab_definition(refs: dict) -> tuple[dict, dict]:
    """Reconstruct input/output for VOCAB_DEFINITION call type."""
    word_entry_id = refs["word_entry_id"]
    cefr_level = refs["cefr_level"]

    word = await VocabularyWord.find_one({"entry_id": word_entry_id})
    if word is None:
        return {"error": "VocabularyWord not found"}, {}

    defn = await VocabularyWordDefinition.find_one(
        {"word.$id": word.id, "student_level": cefr_level}
    )
    if defn is None:
        return {"error": "VocabularyWordDefinition not found"}, {}

    input_snapshot = {
        "word": word.word,
        "pos": word.part_of_speech,
        "senses": [s.model_dump() for s in word.senses[:5]],
    }
    actual_output = {
        "translation": defn.translation,
        "senses": [s.model_dump() for s in defn.senses],
    }
    return input_snapshot, actual_output


async def _reconstruct_grammar_explanation(refs: dict) -> tuple[dict, dict]:
    """Reconstruct input/output for GRAMMAR_EXPLANATION call type."""
    grammar_point_code = refs["grammar_point_code"]
    cefr_level = refs["cefr_level"]

    gp = await GrammarPoint.find_one({"code": grammar_point_code})
    if gp is None:
        return {"error": "GrammarPoint not found"}, {}

    lang = explanation_lang_for_level(cefr_level)
    fallback_lang = "it" if lang == "en" else "en"
    expl = gp.explanations.get(lang) or gp.explanations.get(fallback_lang)
    if expl is None:
        return {"error": "GrammarPointExplanation not found"}, {}

    input_snapshot = {
        "code": gp.code,
        "label": gp.label,
    }
    actual_output = {
        "title": expl.title,
        "explanation": expl.explanation,
    }
    return input_snapshot, actual_output


async def _reconstruct_lesson_plan(refs: dict) -> tuple[dict, dict]:
    """Reconstruct input/output for LESSON_PLAN call type."""
    lesson_id = PydanticObjectId(refs["lesson_id"])
    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        return {"error": "Lesson not found"}, {}

    input_snapshot = {
        "scenario_slug": lesson.scenario_slug,
        "cefr_at_start": lesson.cefr_at_start,
        "duration_minutes": lesson.duration_minutes,
    }
    actual_output = {
        "topic_title": lesson.topic_title,
        "topic_description": lesson.topic_description,
        "activity_count": len(lesson.activities),
        "activity_types": [a.type for a in lesson.activities],
    }
    return input_snapshot, actual_output


_RECONSTRUCTORS = {
    CallType.ANALYZER: _reconstruct_analyzer,
    CallType.SCORER_MULTI: _reconstruct_scorer_multi,
    CallType.SCORER_SINGLE: _reconstruct_scorer_single,
    CallType.LESSON_FEEDBACK: _reconstruct_lesson_feedback,
    CallType.VOCAB_DEFINITION: _reconstruct_vocab_definition,
    CallType.GRAMMAR_EXPLANATION: _reconstruct_grammar_explanation,
    CallType.LESSON_PLAN: _reconstruct_lesson_plan,
}


@router.post("/flag", response_class=HTMLResponse)
async def flag(
    request: Request,
    call_type: Annotated[str, Form()],
    url: Annotated[str, Form()],
    refs: Annotated[str, Form()],
    issue_description: Annotated[str, Form(max_length=2000)] = "",
    student: Student = Depends(get_current_student),
):
    """Flag an LLM call for review. Requires login."""
    try:
        call_type_enum = CallType(call_type)
    except ValueError:
        logger.warning("flag: unknown call_type=%s", call_type)
        return HTMLResponse(f"Unknown call_type: {call_type}", status_code=400)

    try:
        refs_dict = json.loads(refs)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("flag: invalid refs JSON: %s", exc)
        return HTMLResponse(f"Invalid refs JSON: {exc}", status_code=400)

    prompt_version = _prompt_version_for_call_type(call_type_enum)

    reconstructor = _RECONSTRUCTORS.get(call_type_enum)
    if reconstructor is None:
        input_snapshot: dict = {}
        actual_output: dict = {}
    else:
        try:
            input_snapshot, actual_output = await reconstructor(refs_dict)
        except Exception as exc:
            logger.exception("flag: reconstruction failed for %s", call_type)
            input_snapshot = {"error": str(exc)}
            actual_output = {}

    critique = LLMCritique(
        call_type=call_type_enum,
        url=url,
        refs=refs_dict,
        prompt_version=prompt_version,
        input_snapshot=input_snapshot,
        actual_output=actual_output,
        issue_description=issue_description,
    )
    await critique.insert()
    logger.info(
        "flag: created LLMCritique id=%s call_type=%s",
        critique.id,
        call_type,
    )

    return HTMLResponse('<span class="flag-confirm">Flagged &#10003;</span>')
