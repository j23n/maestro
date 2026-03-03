"""
Aggregate LearningEvents into a LearningProfile and generate
a natural-language description for the system prompt.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maestro.models import LearningEvent

from maestro.models import LearningProfile, VocabularyWord, UserVocabularyCard
from maestro.utils import CEFR_ORDER, DATA_DIR


def _load_grammar_points() -> list[dict]:
    with open(DATA_DIR / "grammar_points.json") as f:
        return json.load(f)


async def update_profile(event: "LearningEvent") -> None:
    profile = await LearningProfile.find_one()
    if profile is None:
        profile = LearningProfile()
        await profile.insert()

    for code in event.grammar_correct:
        profile.grammar_correct_counts[code] = profile.grammar_correct_counts.get(code, 0) + 1
    for code in event.grammar_errors:
        profile.grammar_error_counts[code] = profile.grammar_error_counts.get(code, 0) + 1
    for code in event.functions_performed:
        profile.functions_counts[code] = profile.functions_counts.get(code, 0) + 1
    for theme in event.themes:
        if theme not in profile.themes_seen:
            profile.themes_seen.append(theme)

    profile.cefr_estimate = _compute_cefr(profile)
    profile.description = await _generate_description(profile)
    profile.updated_at = datetime.utcnow()
    await profile.save()


def _compute_cefr(profile: "LearningProfile") -> str:
    """Highest CEFR level where ≥60% of that level's grammar points are correct ≥3 times."""
    grammar_points = _load_grammar_points()
    points_by_level: dict[str, list[str]] = {}
    for gp in grammar_points:
        points_by_level.setdefault(gp["cefr_level"], []).append(gp["code"])

    best = "A1"
    for level in CEFR_ORDER:
        codes = points_by_level.get(level, [])
        if not codes:
            continue
        mastered = sum(
            1 for c in codes if profile.grammar_correct_counts.get(c, 0) >= 3
        )
        if mastered / len(codes) >= 0.6:
            best = level
    return best


async def _generate_description(profile: "LearningProfile") -> str:
    # Build code → label lookup from the same JSON used by _compute_cefr
    gp_labels = {gp["code"]: gp["label"] for gp in _load_grammar_points()}

    # Grammar narrative
    demonstrated = [
        gp_labels.get(c, c) for c, n in profile.grammar_correct_counts.items() if n >= 3
    ][:4]
    struggling = [
        gp_labels.get(c, c) for c in profile.grammar_error_counts
        if profile.grammar_error_counts[c] / max(
            1,
            profile.grammar_correct_counts.get(c, 0) + profile.grammar_error_counts[c]
        ) > 0.4
    ][:3]

    # Vocab coverage
    total_by_level: dict[str, int] = {}
    discovered_by_level: dict[str, int] = {}

    all_vocab = await VocabularyWord.find_all().to_list()
    for w in all_vocab:
        total_by_level[w.cefr_level] = total_by_level.get(w.cefr_level, 0) + 1

    cards = await UserVocabularyCard.find_all().to_list()
    for card in cards:
        await card.fetch_all_links()
        lvl = card.word.cefr_level
        discovered_by_level[lvl] = discovered_by_level.get(lvl, 0) + 1

    def pct(level: str) -> int:
        total = total_by_level.get(level, 0)
        if total == 0:
            return 0
        return round(discovered_by_level.get(level, 0) / total * 100)

    a1_pct = pct("A1")
    a2_pct = pct("A2")

    s1 = (
        f"The student is at approximately {profile.cefr_estimate} level"
        + (f", having demonstrated: {', '.join(demonstrated)}." if demonstrated else ".")
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
    return f"{s1} {s2}"
