"""
Aggregate LearningEvents into a LearningProfile and generate
a natural-language description for the system prompt.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maestro.models import LearningEvent

from maestro.models import (
    CommunicativeFunction,
    GrammarPoint,
    LearningProfile,
    UserVocabularyCard,
    VocabularyWord,
)
from maestro.utils import CEFR_ORDER


async def update_profile(event: "LearningEvent") -> None:
    profile = await LearningProfile.find_one()
    if profile is None:
        profile = LearningProfile()
        await profile.insert()

    for code in event.grammar_correct:
        profile.grammar_correct_counts[code] = profile.grammar_correct_counts.get(code, 0) + 1
        recent = profile.grammar_recent_outcomes.get(code, [])
        profile.grammar_recent_outcomes[code] = (recent + [True])[-10:]
    for code in event.grammar_errors:
        profile.grammar_error_counts[code] = profile.grammar_error_counts.get(code, 0) + 1
        recent = profile.grammar_recent_outcomes.get(code, [])
        profile.grammar_recent_outcomes[code] = (recent + [False])[-10:]
    for code in event.functions_performed:
        profile.functions_counts[code] = profile.functions_counts.get(code, 0) + 1
    for theme in event.themes:
        if theme not in profile.themes_seen:
            profile.themes_seen.append(theme)

    profile.cefr_estimate = await _compute_cefr(profile)
    profile.description = await _generate_description(profile)
    profile.updated_at = datetime.utcnow()
    await profile.save()


async def _compute_cefr(profile: "LearningProfile") -> str:
    """Highest CEFR level where ≥90% of GPs are mastered AND ≥90% of CFs are demonstrated."""
    grammar_points = await GrammarPoint.find_all().to_list()
    comm_functions = await CommunicativeFunction.find_all().to_list()

    gp_by_level: dict[str, list[str]] = {}
    for gp in grammar_points:
        gp_by_level.setdefault(gp.cefr_level, []).append(gp.code)

    cf_by_level: dict[str, list[str]] = {}
    for cf in comm_functions:
        cf_by_level.setdefault(cf.cefr_level, []).append(cf.code)

    def _gp_mastered(code: str) -> bool:
        recent = profile.grammar_recent_outcomes.get(code, [])
        return len(recent) >= 5 and sum(recent) / len(recent) >= 0.8

    def _cf_demonstrated(code: str) -> bool:
        return profile.functions_counts.get(code, 0) >= 3

    best = "A1"
    for level in CEFR_ORDER:
        gp_codes = gp_by_level.get(level, [])
        gp_ok = (
            sum(1 for c in gp_codes if _gp_mastered(c)) / max(1, len(gp_codes)) >= 0.9
            if gp_codes else True
        )
        cf_codes = cf_by_level.get(level, [])
        cf_ok = (
            sum(1 for c in cf_codes if _cf_demonstrated(c)) / max(1, len(cf_codes)) >= 0.9
            if cf_codes else True
        )
        if gp_ok and cf_ok:
            best = level

    return best


async def _generate_description(profile: "LearningProfile") -> str:
    grammar_points = await GrammarPoint.find_all().to_list()
    gp_labels = {gp.code: gp.label for gp in grammar_points}

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
        if w.cefr_level is not None:
            total_by_level[w.cefr_level] = total_by_level.get(w.cefr_level, 0) + 1

    cards = await UserVocabularyCard.find_all().to_list()
    for card in cards:
        await card.fetch_all_links()
        lvl = card.word.cefr_level
        if lvl is not None:
            discovered_by_level[lvl] = discovered_by_level.get(lvl, 0) + 1

    def pct(level: str) -> int:
        total = total_by_level.get(level, 0)
        if total == 0:
            return 0
        return round(discovered_by_level.get(level, 0) / total * 100)

    a1_pct = pct("A1")
    a2_pct = pct("A2")

    # Communicative functions narrative
    comm_functions = await CommunicativeFunction.find_all().to_list()
    cf_by_code = {cf.code: cf for cf in comm_functions}

    macro_counts: dict[str, int] = {}
    for code, count in profile.functions_counts.items():
        cf = cf_by_code.get(code)
        if cf:
            macro_counts[cf.macro_category] = macro_counts.get(cf.macro_category, 0) + count

    top_functions = sorted(profile.functions_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    top_function_labels = [
        cf_by_code[code].label for code, _ in top_functions if code in cf_by_code
    ]
    top_macros = sorted(macro_counts, key=macro_counts.get, reverse=True)[:2]  # type: ignore[arg-type]

    _MACRO_LABELS = {
        "interagire_informazioni": "exchanging information",
        "interagire_opinioni_atteggiamenti": "expressing opinions",
        "interagire_emozioni_sentimenti": "expressing emotions",
        "interagire_attivita_azioni": "coordinating actions",
        "interagire_rituali_sociali": "social rituals",
        "strutturare_discorso": "structuring discourse",
        "strutturare_interazione_verbale": "managing conversation",
    }

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

    if top_function_labels:
        macro_str = (
            " and ".join(_MACRO_LABELS.get(m, m) for m in top_macros)
            if top_macros else ""
        )
        s3 = (
            f"Communicative repertoire: mainly {macro_str}; "
            f"most used: {', '.join(top_function_labels)}."
        )
    else:
        s3 = ""

    return " ".join(filter(None, [s1, s2, s3]))
