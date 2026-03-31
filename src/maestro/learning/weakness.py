"""Shared helpers for computing grammar weaknesses from a student profile."""

from __future__ import annotations

from maestro.models import GrammarPoint, LearningProfile
from maestro.utils import CEFR_ORDER, explanation_lang_for_level, strip_lang_spans


def build_grammar_by_level(
    grammar_points: list[GrammarPoint],
    profile: LearningProfile | None,
    gp_titles: dict[str, str],
) -> dict[str, list[dict]]:
    """Build a {level: [skill_dict, ...]} mapping for all grammar points."""
    grammar_by_level: dict[str, list[dict]] = {}
    for level in CEFR_ORDER:
        points = [p for p in grammar_points if p.cefr_level == level]
        skills = []
        for p in points:
            lp = profile.active_progress if profile else None
            correct = lp.grammar_correct_counts.get(p.code, 0) if lp else 0
            errors = lp.grammar_error_counts.get(p.code, 0) if lp else 0
            recent = lp.grammar_recent_outcomes.get(p.code, []) if lp else []
            mastered = (
                lp.grammar_mastery_scores.get(p.code, 0.0) >= 0.8 if lp else False
            )
            title = gp_titles.get(p.code, "")
            skills.append(
                {
                    "point": p,
                    "title": title,
                    "correct": correct,
                    "errors": errors,
                    "mastered": mastered,
                    "recent": recent,
                }
            )
        grammar_by_level[level] = skills
    return grammar_by_level


def build_gp_titles(
    grammar_points: list[GrammarPoint],
    cefr: str,
    target_language: str = "it",
) -> dict[str, str]:
    """Build a {gp_code: explanation_title} map using inline GP explanations."""
    lang = explanation_lang_for_level(cefr, target_language)
    fallback_lang = target_language if lang == "en" else "en"
    gp_titles: dict[str, str] = {}
    for gp in grammar_points:
        expl = gp.explanations.get(lang) or gp.explanations.get(fallback_lang)
        gp_titles[gp.code] = strip_lang_spans(expl.title) if expl else gp.label
    return gp_titles


def top_weaknesses(
    grammar_by_level: dict[str, list[dict]],
    cefr: str,
    n: int = 3,
) -> list[dict]:
    """Return the top N grammar weaknesses at the student's current level."""
    skills = grammar_by_level.get(cefr, [])
    weak = []
    for s in skills:
        total = s["correct"] + s["errors"]
        if total < 2:
            continue
        error_rate = s["errors"] / total
        if error_rate > 0.3:
            label = s["title"] or s["point"].label
            weak.append(
                {
                    "label": label,
                    "code": s["point"].code,
                    "error_rate": error_rate,
                    "total": total,
                }
            )
    weak.sort(key=lambda w: w["error_rate"], reverse=True)
    return weak[:n]
