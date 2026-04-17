"""Feedback routes — LLM critique flagging.

Call types fall into two groups:

* **Metadata-only** (``lesson_plan``, ``vocab_definition``, ``grammar_explanation``) —
  the flag request identifies a persisted entity via ``refs``; the server
  rebuilds the input/output from stored metadata that contains no student
  content.

* **PPI-adjacent** (``analyzer``, ``scorer_single``, ``scorer_multi``) — we no
  longer persist student text or scoring prose, so the client must include the
  reviewer's local snapshot of the inputs and outputs as ``input_snapshot`` and
  ``actual_output`` form fields (JSON). The server accepts them verbatim.
"""

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
    GrammarPoint,
    Lesson,
    LLMCritique,
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
    if call_type == CallType.ANALYZER:
        return _prompts.analyzer.version
    if call_type in (CallType.SCORER_SINGLE, CallType.SCORER_MULTI):
        return _prompts.scorer.version
    if call_type == CallType.LESSON_PLAN:
        return _prompts.planner.version
    if call_type in (CallType.LESSON_ANALYZER_CF1, CallType.LESSON_ANALYZER_CF2):
        return _prompts.lesson_analyzer.version
    if call_type == CallType.VOCAB_DEFINITION:
        return _prompts.vocab.version
    if call_type == CallType.GRAMMAR_EXPLANATION:
        return _prompts.grammar.version
    return "unknown"


# --- Server-side reconstructors for metadata-only call types --------------


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

    lang = explanation_lang_for_level(cefr_level, gp.language)
    fallback_lang = gp.language if lang == "en" else "en"
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
    CallType.VOCAB_DEFINITION: _reconstruct_vocab_definition,
    CallType.GRAMMAR_EXPLANATION: _reconstruct_grammar_explanation,
    CallType.LESSON_PLAN: _reconstruct_lesson_plan,
}

# Call types that require the client to submit input_snapshot/actual_output.
# We do not persist the underlying student content, so reconstruction from the
# database is impossible.
_CLIENT_SNAPSHOT_CALL_TYPES = {
    CallType.ANALYZER,
    CallType.SCORER_SINGLE,
    CallType.SCORER_MULTI,
    CallType.LESSON_ANALYZER_CF1,
    CallType.LESSON_ANALYZER_CF2,
}


def _parse_json_dict(raw: str, field_name: str) -> tuple[dict | None, str | None]:
    if not raw:
        return {}, None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"Invalid {field_name} JSON: {exc}"
    if not isinstance(value, dict):
        return None, f"{field_name} must be a JSON object"
    return value, None


@router.post("/flag", response_class=HTMLResponse)
async def flag(
    request: Request,
    call_type: Annotated[str, Form()],
    url: Annotated[str, Form()],
    refs: Annotated[str, Form()],
    issue_description: Annotated[str, Form(max_length=2000)] = "",
    input_snapshot: Annotated[str, Form(max_length=20000)] = "",
    actual_output: Annotated[str, Form(max_length=20000)] = "",
    student: Student = Depends(get_current_student),
):
    """Flag an LLM call for review. Requires login.

    For call types that touch student content we never persist, the caller
    must pass ``input_snapshot`` and ``actual_output`` as JSON form fields.
    """
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

    client_input, err = _parse_json_dict(input_snapshot, "input_snapshot")
    if err:
        return HTMLResponse(err, status_code=400)
    client_output, err = _parse_json_dict(actual_output, "actual_output")
    if err:
        return HTMLResponse(err, status_code=400)

    reconstructor = _RECONSTRUCTORS.get(call_type_enum)
    if reconstructor is not None:
        try:
            rebuilt_input, rebuilt_output = await reconstructor(refs_dict)
        except Exception as exc:
            logger.exception("flag: reconstruction failed for %s", call_type)
            rebuilt_input = {"error": str(exc)}
            rebuilt_output = {}
        # Client-supplied snapshot (if any) takes precedence over rebuilt.
        final_input = client_input or rebuilt_input
        final_output = client_output or rebuilt_output
    elif call_type_enum in _CLIENT_SNAPSHOT_CALL_TYPES:
        final_input = client_input or {}
        final_output = client_output or {}
    else:
        final_input = client_input or {}
        final_output = client_output or {}

    critique = LLMCritique(
        call_type=call_type_enum,
        url=url,
        refs=refs_dict,
        prompt_version=prompt_version,
        input_snapshot=final_input,
        actual_output=final_output,
        issue_description=issue_description,
    )
    await critique.insert()
    logger.info(
        "flag: created LLMCritique id=%s call_type=%s",
        critique.id,
        call_type,
    )

    return HTMLResponse('<span class="flag-confirm">Flagged &#10003;</span>')
