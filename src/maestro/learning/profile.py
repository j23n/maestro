"""
Per-student learning profile access and aggregation.

Provides helpers to get/create profiles, and aggregates LearningEvents
into a LearningProfile with a natural-language description for the system prompt.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from beanie import PydanticObjectId

if TYPE_CHECKING:
    from maestro.models import LearningEvent, Student

from maestro.learning import grammar_cache
from maestro.learning.constants import MACRO_CATEGORIES as _MACRO_TUPLES
from maestro.models import (
    CurriculumScenario,
    LearningProfile,
    ScenarioProgress,
    UserVocabularyCard,
    VocabularyWord,
)
from maestro.utils import CEFR_ORDER, utcnow

logger = logging.getLogger(__name__)

_MACRO_LABELS = {k: v[1] for k, v in _MACRO_TUPLES.items()}


async def get_profile(student_id: PydanticObjectId) -> LearningProfile | None:
    """Return the LearningProfile for a student, or None if not yet created."""
    return await LearningProfile.find_one({"student_id": student_id})


async def get_or_create_profile(
    student_id: PydanticObjectId,
    *,
    target_language: str | None = None,
) -> LearningProfile:
    """Return the LearningProfile for a student, creating an empty one if needed."""
    profile = await LearningProfile.find_one({"student_id": student_id})
    if profile is None:
        kwargs: dict = {"student_id": student_id}
        if target_language is not None:
            kwargs["target_language"] = target_language
        profile = LearningProfile(**kwargs)
        await profile.insert()
    return profile


async def get_cefr_level(student_id: PydanticObjectId) -> str:
    """Return the student's current CEFR estimate, defaulting to 'A0'."""
    profile = await get_profile(student_id)
    return profile.cefr_estimate if profile else "A0"


async def save_onboarding_field(
    student: "Student", profile_field: str, answer: str
) -> None:
    """Save an onboarding answer to the appropriate student/profile field."""
    if not answer.strip():
        return

    answer = answer.strip()

    if profile_field == "name":
        student.name = answer[:30]
        await student.save()
    elif profile_field in ("background", "interests", "goal"):
        profile = await get_or_create_profile(student.id)
        existing = getattr(profile.persona, profile_field, "")
        if existing:
            setattr(profile.persona, profile_field, f"{existing}, {answer}")
        else:
            setattr(profile.persona, profile_field, answer)
        await profile.save()


def outcome_ok(r) -> bool:
    """Extract the boolean from a recent-outcome entry (handles both old bool and new dict)."""
    return r["ok"] if isinstance(r, dict) else r


async def update_profile(event: "LearningEvent") -> None:
    profile = await get_or_create_profile(event.student_id)
    now = utcnow().isoformat()

    for code in event.grammar_correct:
        profile.grammar_correct_counts[code] = (
            profile.grammar_correct_counts.get(code, 0) + 1
        )
        recent = profile.grammar_recent_outcomes.get(code, [])
        profile.grammar_recent_outcomes[code] = (recent + [{"ok": True, "ts": now}])[
            -10:
        ]
    for code in event.grammar_errors:
        profile.grammar_error_counts[code] = (
            profile.grammar_error_counts.get(code, 0) + 1
        )
        recent = profile.grammar_recent_outcomes.get(code, [])
        profile.grammar_recent_outcomes[code] = (recent + [{"ok": False, "ts": now}])[
            -10:
        ]
    for code in event.functions_performed:
        profile.functions_counts[code] = profile.functions_counts.get(code, 0) + 1
    for theme in event.themes:
        if theme not in profile.themes_seen:
            profile.themes_seen.append(theme)

    # Recompute weighted mastery for affected GP codes
    from maestro.learning.mastery import compute_gp_mastery

    affected_codes = set(event.grammar_correct) | set(event.grammar_errors)
    for code in affected_codes:
        profile.grammar_mastery_scores[code] = await compute_gp_mastery(
            event.student_id, code
        )
    if affected_codes:
        logger.info(
            "mastery recomputed for %d GP codes, student=%s",
            len(affected_codes),
            event.student_id,
        )

    old_cefr = profile.cefr_estimate
    profile.cefr_estimate = await _compute_cefr(profile)
    if profile.cefr_estimate != old_cefr:
        logger.info(
            "CEFR level changed %s -> %s, student=%s",
            old_cefr,
            profile.cefr_estimate,
            event.student_id,
        )
    profile.description = await _generate_description(profile)
    profile.updated_at = utcnow()
    await profile.save()


async def _compute_cefr(profile: "LearningProfile") -> str:
    """Highest CEFR level where ≥90% of GPs are mastered AND ≥90% of CFs are demonstrated.

    A0 graduation: all A0 scenarios must be completed (depth >= 1).

    Note: may mutate ``profile.onboarding_completed``; caller must save.
    """
    # A0 check: have all A0 scenarios been completed?
    if not (profile.onboarding_completed or profile.onboarding_skipped):
        a0_scenarios = await CurriculumScenario.find(
            {"cefr_level": "A0", "language": profile.target_language}
        ).to_list()
        if a0_scenarios:
            progress = profile.scenario_progress or {}
            for scenario in a0_scenarios:
                sp = progress.get(scenario.slug, ScenarioProgress())
                if sp.depth < 1:
                    return "A0"
        # All A0 scenarios done — mark onboarding as completed
        profile.onboarding_completed = True

    lang = profile.target_language
    await grammar_cache.ensure_loaded(lang)
    grammar_points = grammar_cache.grammar_points(lang)
    comm_functions = grammar_cache.comm_functions(lang)

    gp_by_level: dict[str, list[str]] = {}
    for gp in grammar_points:
        gp_by_level.setdefault(gp.cefr_level, []).append(gp.code)

    cf_by_level: dict[str, list[str]] = {}
    for cf in comm_functions:
        cf_by_level.setdefault(cf.cefr_level, []).append(cf.code)

    def _gp_mastered(code: str) -> bool:
        return profile.grammar_mastery_scores.get(code, 0.0) >= 0.8

    def _cf_demonstrated(code: str) -> bool:
        return profile.functions_counts.get(code, 0) >= 3

    best = "A1"
    for level in CEFR_ORDER:
        if level == "A0":
            continue  # A0 graduation handled above
        gp_codes = gp_by_level.get(level, [])
        gp_ok = (
            sum(1 for c in gp_codes if _gp_mastered(c)) / len(gp_codes) >= 0.9
            if gp_codes
            else False
        )
        cf_codes = cf_by_level.get(level, [])
        cf_ok = (
            sum(1 for c in cf_codes if _cf_demonstrated(c)) / len(cf_codes) >= 0.9
            if cf_codes
            else False
        )
        if gp_ok and cf_ok:
            best = level
        else:
            break  # can't skip levels

    return best


async def _generate_description(profile: "LearningProfile") -> str:
    lang = profile.target_language
    await grammar_cache.ensure_loaded(lang)
    gp_labels = {gp.code: gp.label for gp in grammar_cache.grammar_points(lang)}

    # Grammar narrative
    demonstrated = [
        gp_labels.get(c, c) for c, n in profile.grammar_correct_counts.items() if n >= 3
    ][:4]
    struggling = [
        gp_labels.get(c, c)
        for c in profile.grammar_error_counts
        if profile.grammar_error_counts[c]
        / max(
            1,
            profile.grammar_correct_counts.get(c, 0) + profile.grammar_error_counts[c],
        )
        > 0.4
    ][:3]

    # Vocab coverage
    total_by_level: dict[str, int] = {}
    discovered_by_level: dict[str, int] = {}

    all_vocab = await VocabularyWord.find({"cefr_level": {"$ne": None}}).to_list()
    for w in all_vocab:
        total_by_level[w.cefr_level] = total_by_level.get(w.cefr_level, 0) + 1

    # Batch fetch word docs instead of N+1 fetch_all_links()
    card_filter: dict = {"excluded": {"$ne": True}}
    if profile.student_id:
        card_filter["student_id"] = profile.student_id
    cards = await UserVocabularyCard.find(card_filter).to_list()
    word_ids = []
    for card in cards:
        ref = card.word
        word_ids.append(ref.ref.id if hasattr(ref, "ref") else ref.id)

    discovered_words = await VocabularyWord.find({"_id": {"$in": word_ids}}).to_list()
    for w in discovered_words:
        if w.cefr_level is not None:
            discovered_by_level[w.cefr_level] = (
                discovered_by_level.get(w.cefr_level, 0) + 1
            )

    def pct(level: str) -> int:
        total = total_by_level.get(level, 0)
        if total == 0:
            return 0
        return round(discovered_by_level.get(level, 0) / total * 100)

    a1_pct = pct("A1")
    a2_pct = pct("A2")

    # Communicative functions narrative
    cf_by_code = {cf.code: cf for cf in grammar_cache.comm_functions(lang)}

    macro_counts: dict[str, int] = {}
    for code, count in profile.functions_counts.items():
        cf = cf_by_code.get(code)
        if cf:
            macro_counts[cf.macro_category] = (
                macro_counts.get(cf.macro_category, 0) + count
            )

    top_functions = sorted(
        profile.functions_counts.items(), key=lambda x: x[1], reverse=True
    )[:3]
    top_function_labels = [
        cf_by_code[code].label for code, _ in top_functions if code in cf_by_code
    ]
    top_macros = sorted(macro_counts, key=macro_counts.get, reverse=True)[:2]  # type: ignore[arg-type]

    s1 = f"The student is at approximately {profile.cefr_estimate} level" + (
        f", having demonstrated: {', '.join(demonstrated)}." if demonstrated else "."
    )
    if struggling:
        s2 = (
            f"Persistent difficulties: {', '.join(struggling)}; "
            f"{a1_pct}% of A1 and {a2_pct}% of A2 vocabulary encountered."
        )
    else:
        s2 = (
            f"{a1_pct}% of A1 and {a2_pct}% of A2 vocabulary encountered; "
            "no persistent errors yet."
        )

    if top_function_labels:
        macro_str = (
            " and ".join(_MACRO_LABELS.get(m, m) for m in top_macros)
            if top_macros
            else ""
        )
        s3 = (
            f"Communicative repertoire: mainly {macro_str}; "
            f"most used: {', '.join(top_function_labels)}."
        )
    else:
        s3 = ""

    return " ".join(filter(None, [s1, s2, s3]))
