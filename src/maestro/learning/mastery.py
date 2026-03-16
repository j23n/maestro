"""Weighted mastery computation for grammar points.

Replaces the flat sliding-window model with evidence-weighted, time-decayed
mastery scores computed from per-activity LearningEvents.
"""

from __future__ import annotations

from datetime import timezone

from maestro.models import LearningEvent
from maestro.utils import utcnow

# Evidence type weights: productive use (writing/speaking) is stronger evidence
# than targeted drill practice, which is stronger than receptive (reading).
EVIDENCE_WEIGHTS: dict[str | None, float] = {
    "targeted": 1.0,
    "productive": 1.5,
    "receptive": 0.5,
}

DECAY_BASE = 0.95  # per-day decay factor (30 days ago ≈ 21% weight)
MASTERY_THRESHOLD = 0.8
MIN_WEIGHTED_DENOM = 3.0  # minimum evidence mass before scoring
_EVENT_LIMIT = 50  # cap per-GP query for performance


async def compute_gp_mastery(student_id, gp_code: str) -> float:
    """Compute weighted mastery score for a single grammar point.

    Returns a float in [-1.0, 1.0]. Values below 0 indicate net-negative
    evidence; values at or above MASTERY_THRESHOLD indicate mastery.
    Returns 0.0 if insufficient evidence (denominator < MIN_WEIGHTED_DENOM).
    """
    now = utcnow()
    events = (
        await LearningEvent.find(
            {
                "student_id": student_id,
                "evidence_type": {"$ne": None},
                "$or": [
                    {"grammar_correct": gp_code},
                    {"grammar_errors": gp_code},
                ],
            }
        )
        .sort("-created_at")
        .limit(_EVENT_LIMIT)
        .to_list()
    )

    if not events:
        return 0.0

    numerator = 0.0
    denominator = 0.0

    for ev in events:
        weight = EVIDENCE_WEIGHTS.get(ev.evidence_type, 1.0)
        created = ev.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        days_ago = (now - created).total_seconds() / 86400
        decay = DECAY_BASE**days_ago
        weighted = weight * decay

        if gp_code in ev.grammar_correct:
            numerator += weighted
        if gp_code in ev.grammar_errors:
            numerator -= weighted
        denominator += weighted

    if denominator < MIN_WEIGHTED_DENOM:
        return 0.0

    return numerator / denominator


def is_mastered(score: float) -> bool:
    """Check if a mastery score meets the threshold."""
    return score >= MASTERY_THRESHOLD
