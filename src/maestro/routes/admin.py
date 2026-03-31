import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from maestro.auth import get_admin_account
from maestro.models import (
    Account,
    DrillAttempt,
    Lesson,
    LessonStatus,
    LearningProfile,
    LLMCritique,
    LLMUsageRecord,
    UserVocabularyCard,
)
from maestro.templates import render
from maestro.utils import utcnow

router = APIRouter(prefix="/admin")


async def _user_stats(account: Account) -> dict:
    """Gather per-user stats for a single account."""
    sid = account.student_id

    lessons_q = Lesson.find(
        {"student_id": sid, "status": LessonStatus.COMPLETED}
    ).count()
    profile_q = LearningProfile.find_one({"student_id": sid})
    # Intentionally not filtered by language — admin overview shows cross-language totals
    vocab_known_q = UserVocabularyCard.find(
        {"student_id": sid, "interval": {"$gte": 14}, "excluded": {"$ne": True}}
    ).count()
    vocab_total_q = UserVocabularyCard.find(
        {"student_id": sid, "excluded": {"$ne": True}}
    ).count()
    drill_q = DrillAttempt.find({"student_id": sid}).to_list()
    cost_q = LLMUsageRecord.find({"student_id": sid}).to_list()

    (
        lessons,
        profile,
        vocab_known,
        vocab_total,
        drills,
        cost_records,
    ) = await asyncio.gather(
        lessons_q, profile_q, vocab_known_q, vocab_total_q, drill_q, cost_q
    )

    drill_total = len(drills)
    drill_correct = sum(1 for d in drills if d.correct)
    if drill_total:
        pct = round(100 * drill_correct / drill_total)
        drill_accuracy = f"{drill_correct}/{drill_total} ({pct}%)"
    else:
        drill_accuracy = "\u2014"

    llm_cost = sum(r.cost_usd for r in cost_records)

    return {
        "lessons_completed": lessons,
        "cefr": profile.active_progress.cefr_estimate if profile else "A0",
        "vocab_known": vocab_known,
        "vocab_total": vocab_total,
        "drill_accuracy": drill_accuracy,
        "llm_cost": llm_cost,
        "last_active": profile.updated_at if profile else None,
        "signup_date": account.created_at,
        "tier": account.subscription_tier,
    }


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request, account: Account = Depends(get_admin_account)
):
    now = utcnow()
    week_ago = now - timedelta(days=7)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # --- Global stats (parallel, using simple find queries) ---
    total_users_q = Account.find().count()
    signups_week_q = Account.find({"created_at": {"$gte": week_ago}}).count()
    lessons_today_q = Lesson.find(
        {"status": LessonStatus.COMPLETED, "completed_at": {"$gte": today_start}}
    ).count()
    completed_q = Lesson.find({"status": LessonStatus.COMPLETED}).count()
    abandoned_q = Lesson.find({"status": LessonStatus.ABANDONED}).count()
    recent_usage_q = LLMUsageRecord.find({"created_at": {"$gte": week_ago}}).to_list()
    recent_lessons_q = Lesson.find({"created_at": {"$gte": week_ago}}).to_list()

    (
        total_users,
        signups_week,
        lessons_today,
        completed_count,
        abandoned_count,
        recent_usage,
        recent_lessons,
    ) = await asyncio.gather(
        total_users_q,
        signups_week_q,
        lessons_today_q,
        completed_q,
        abandoned_q,
        recent_usage_q,
        recent_lessons_q,
    )

    active_users_7d = len({lesson.student_id for lesson in recent_lessons})

    total_final = completed_count + abandoned_count
    completion_rate = round(100 * completed_count / total_final) if total_final else 0

    llm_spend_week = sum(r.cost_usd for r in recent_usage)

    # LLM cost breakdown by call_type
    breakdown: dict[str, dict] = {}
    for r in recent_usage:
        key = r.call_type.value if hasattr(r.call_type, "value") else r.call_type
        if key not in breakdown:
            breakdown[key] = {
                "call_type": key,
                "call_count": 0,
                "total_tokens": 0,
                "total_cost": 0.0,
            }
        breakdown[key]["call_count"] += 1
        breakdown[key]["total_tokens"] += r.input_tokens + r.output_tokens
        breakdown[key]["total_cost"] += r.cost_usd
    llm_breakdown = sorted(
        breakdown.values(), key=lambda r: r["total_cost"], reverse=True
    )

    # --- Per-user stats ---
    accounts = await Account.find().to_list()
    user_rows = list(await asyncio.gather(*[_user_stats(a) for a in accounts]))
    user_rows.sort(
        key=lambda r: (
            r["last_active"].replace(tzinfo=None) if r["last_active"] else datetime.min
        ),
        reverse=True,
    )
    for i, row in enumerate(user_rows, 1):
        row["label"] = i

    return render(
        request,
        "admin-dashboard.html",
        {
            "total_users": total_users,
            "signups_week": signups_week,
            "active_users_7d": active_users_7d,
            "lessons_today": lessons_today,
            "completion_rate": completion_rate,
            "llm_spend_week": llm_spend_week,
            "user_rows": user_rows,
            "llm_breakdown": llm_breakdown,
        },
    )


@router.get("/feedback", response_class=HTMLResponse)
async def admin_feedback(
    request: Request, account: Account = Depends(get_admin_account)
):
    critiques = await LLMCritique.find().sort("-created_at").limit(50).to_list()
    return render(request, "admin-feedback.html", {"critiques": critiques})
