"""XML-tagged section builders for the lesson planner user prompt.

Each builder returns an `<tag>...</tag>` string (or empty string when the
section doesn't apply to this lesson). The orchestrator in `prompts.py`
assembles the result by concatenation — keeping section logic isolated
makes each piece independently testable.
"""

from __future__ import annotations

import json
from typing import Optional

from maestro.learning.mastery import mastery_label
from maestro.models import (
    CommunicativeFunction,
    CurriculumScenario,
    GrammarPoint,
    LearningProfile,
    Lesson,
    StudentPersona,
)


def section_student(
    *,
    cefr_level: str,
    persona_lines: list[str],
    lesson_context: str,
    profile: Optional[LearningProfile],
) -> str:
    lines = [f"Estimated level: {cefr_level}"]
    if persona_lines:
        lines.append("Persona (use only if it fits the scenario naturally):")
        lines.extend(f"  {line}" for line in persona_lines)
    if lesson_context:
        lines.append(f"Lesson context requested by the student: {lesson_context}")
    if profile and profile.active_progress.description:
        lines.append(f"Recent narrative: {profile.active_progress.description}")
    return _wrap("student", "\n".join(lines))


def pick_persona_lines(
    persona: Optional[StudentPersona],
    *,
    rng,
) -> list[str]:
    """Return 0-2 persona field lines for inclusion in <student>.

    Stochastic: ~70% inclusion rate, then 1-2 fields sampled at random.
    `rng` is a `random` module (or compatible) — exposed so tests can monkeypatch.
    """
    if not persona or rng.random() >= 0.7:
        return []
    field_map = {
        "background": ("Background", persona.background),
        "interests": ("Interests", persona.interests),
        "goal": ("Goal", persona.goal),
    }
    available = [k for k, (_, v) in field_map.items() if v]
    if not available:
        return []
    pick_count = min(len(available), rng.randint(1, 2))
    chosen = rng.sample(available, pick_count)
    return [f"{field_map[k][0]}: {field_map[k][1]}" for k in chosen]


def section_recent_lessons(lessons: list[Lesson]) -> str:
    if not lessons:
        return ""
    lines = []
    for lesson in lessons:
        title = lesson.topic_title or "(untitled)"
        desc = (lesson.topic_description or "").strip()
        archetype = f" ({lesson.archetype})" if lesson.archetype else ""
        lines.append(f'  - "{title}" — {desc}{archetype}')
    return _wrap("recent_lessons", "\n".join(lines))


def section_storyline(storyline: str, *, stale: bool = False) -> str:
    """Render the student's evolving storyline so the LLM can thread it
    through the lesson setup with natural callbacks.

    When `stale` is True (last lesson > STORYLINE_STALE_DAYS ago), append a
    welcome-back hint instructing the model to soften callbacks. The stale
    hint is only emitted alongside a non-empty storyline — there is no
    dangling instruction without context to anchor to.
    """
    text = (storyline or "").strip()
    if not text:
        return ""
    body_lines = [
        "Thread this through the lesson setup where natural — do not restate verbatim, and do not contradict established facts.",
        text,
    ]
    if stale:
        body_lines.append(
            "Note: the student has been away for more than two weeks. Soften any callbacks; do not assume recall of prior specifics."
        )
    return _wrap("storyline", "\n\n".join(body_lines))


def section_scenario(scenario: CurriculumScenario, depth: int) -> str:
    depth_description = (
        scenario.depths[depth - 1]
        if depth <= len(scenario.depths)
        else scenario.depths[-1]
    )
    return _wrap(
        "scenario",
        f'"{scenario.label}" (depth {depth}): {depth_description}',
    )


def section_lesson_shape(
    *,
    archetype_block: str,
    listening_count: int,
    reading_count: int,
    drill_count: int,
    speaking_count: int,
    include_writing: bool,
) -> str:
    lines: list[str] = []
    if archetype_block:
        lines.append(archetype_block.rstrip())
    activity_bits = []
    if listening_count:
        activity_bits.append(f"{listening_count} listening")
    if reading_count:
        activity_bits.append(f"{reading_count} reading")
    if drill_count:
        activity_bits.append(f"{drill_count} drill")
    if speaking_count:
        activity_bits.append(f"{speaking_count} speaking")
    if include_writing:
        activity_bits.append("1 writing")
    if activity_bits:
        lines.append(f"Activities: {', '.join(activity_bits)}.")
    return _wrap("lesson_shape", "\n".join(lines)) if lines else ""


def section_grammar_targets(
    grammar_gps: list[GrammarPoint],
    profile: Optional[LearningProfile],
) -> str:
    if not grammar_gps:
        return ""
    lp = profile.active_progress if profile else None
    lines = []
    for gp in grammar_gps:
        score = lp.grammar_mastery_scores.get(gp.code) if lp else None
        label = mastery_label(score)
        lines.append(f"  - {gp.label} ({gp.code}) — mastery: {label}")
    return _wrap("grammar_targets", "\n".join(lines))


def section_drills(drill_specs: list[dict]) -> str:
    if not drill_specs:
        return ""
    lines = []
    for spec in drill_specs:
        et = spec["exercise_type"]
        et_str = et.value if hasattr(et, "value") else str(et)
        line = f"  - {spec['grammar_point_code']} | {et_str} | {spec['gp_label']}"
        if spec.get("rag_excerpt"):
            line += f"\n    RAG: {spec['rag_excerpt'][:500]}"
        lines.append(line)
    return _wrap("drills", "\n".join(lines))


def section_speaking(speaking_cfs: list[CommunicativeFunction]) -> str:
    if not speaking_cfs:
        return ""
    blocks = []
    for cf in speaking_cfs:
        block = [f"Function: {cf.label} ({cf.code}, {cf.category})"]
        patterns = cf.patterns[:3]
        examples = cf.examples[:3]
        if patterns:
            block.append("Patterns: " + "; ".join(patterns))
        if examples:
            block.append("Examples: " + "; ".join(examples))
        blocks.append("\n".join(block))
    return _wrap("speaking", "\n\n".join(blocks))


def section_output_schema(schema: dict) -> str:
    return _wrap(
        "output_schema",
        "Match this JSON structure (return ONLY this object):\n"
        + json.dumps(schema, indent=2, ensure_ascii=False),
    )


def _wrap(tag: str, body: str) -> str:
    return f"<{tag}>\n{body}\n</{tag}>"
