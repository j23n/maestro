from typing import Annotated

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from maestro.auth import get_current_student
from maestro.models import (
    CommunicativeFunction,
    CurriculumScenario,
    GrammarPoint,
    GrammarPointExplanation,
    Lesson,
    LessonStatus,
    ScenarioProgress,
    Student,
    StudentPersona,
    UserVocabularyCard,
)
from maestro.profile import get_profile, get_or_create_profile
from maestro.templates import templates
from maestro.utils import CEFR_ORDER

router = APIRouter()


def _build_grammar_by_level(grammar_points, profile, gp_titles):
    grammar_by_level = {}
    for level in CEFR_ORDER:
        points = [p for p in grammar_points if p.cefr_level == level]
        skills = []
        for p in points:
            correct = profile.grammar_correct_counts.get(p.code, 0) if profile else 0
            errors = profile.grammar_error_counts.get(p.code, 0) if profile else 0
            recent = profile.grammar_recent_outcomes.get(p.code, []) if profile else []
            mastered = len(recent) >= 5 and sum(recent) / len(recent) >= 0.8
            title = gp_titles.get(p.code, "")
            skills.append({"point": p, "title": title, "correct": correct, "errors": errors, "mastered": mastered, "recent": recent})
        grammar_by_level[level] = skills
    return grammar_by_level


def _top_weaknesses(grammar_by_level, cefr, gp_titles, n=3):
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
            weak.append({"label": label, "code": s["point"].code, "error_rate": error_rate, "total": total})
    weak.sort(key=lambda w: w["error_rate"], reverse=True)
    return weak[:n]


def _build_cf_by_level(comm_functions, profile):
    cf_by_level = {}
    for level in CEFR_ORDER:
        cfs = [cf for cf in comm_functions if cf.cefr_level == level]
        items = []
        for cf in cfs:
            count = profile.functions_counts.get(cf.code, 0) if profile else 0
            items.append({"cf": cf, "count": count, "demonstrated": count >= 3})
        cf_by_level[level] = items
    return cf_by_level


@router.get("/profilo", response_class=HTMLResponse)
async def profilo_page(request: Request, student: Student = Depends(get_current_student)):
    profile = await get_profile(student.id)
    grammar_points = await GrammarPoint.find_all().to_list()
    comm_functions = await CommunicativeFunction.find_all().to_list()

    # Build GP code → explanation title map for the student's current level
    cefr = profile.cefr_estimate if profile else "A0"
    gp_by_id = {gp.id: gp for gp in grammar_points}
    expl_level = cefr if cefr not in ("A0",) else "A1"
    explanations = await GrammarPointExplanation.find(
        {"student_level": expl_level}
    ).to_list()
    gp_titles: dict[str, str] = {}
    for e in explanations:
        ref = e.grammar_point
        gp_id = ref.ref.id if hasattr(ref, "ref") else getattr(ref, "id", None)
        if gp_id and gp_id in gp_by_id:
            gp_titles[gp_by_id[gp_id].code] = e.title

    grammar_by_level = _build_grammar_by_level(grammar_points, profile, gp_titles)
    cf_by_level = _build_cf_by_level(comm_functions, profile)

    # Top weaknesses for the summary
    weaknesses = _top_weaknesses(grammar_by_level, cefr, gp_titles)

    # Profile summary stats
    total_lessons = await Lesson.find(
        {"student_id": student.id, "status": LessonStatus.COMPLETED}
    ).count()
    vocab_known = await UserVocabularyCard.find(
        {"student_id": student.id, "interval": {"$gte": 14}}
    ).count()

    # Top communicative functions
    top_cf_labels = []
    if profile:
        cf_by_code = {cf.code: cf for cf in comm_functions}
        top_cfs = sorted(
            profile.functions_counts.items(), key=lambda x: x[1], reverse=True
        )[:3]
        top_cf_labels = [
            cf_by_code[code].label for code, _ in top_cfs if code in cf_by_code
        ]

    scenarios = await CurriculumScenario.find({"cefr_level": cefr}).to_list()
    # Sort A0 by sequence, others by label
    if cefr == "A0":
        scenarios.sort(key=lambda s: s.sequence or 0)
    else:
        scenarios.sort(key=lambda s: s.label)
    progress = profile.scenario_progress if profile else {}
    _no_progress = ScenarioProgress()
    scenario_map = [
        {
            "scenario": s,
            "depth_completed": progress.get(s.slug, _no_progress).depth,
            "lesson_count": progress.get(s.slug, _no_progress).lesson_count,
            "last_visited": progress.get(s.slug, _no_progress).last_visited,
        }
        for s in scenarios
    ]

    # Lesson history
    recent_lessons = await Lesson.find(
        {"student_id": student.id, "status": LessonStatus.COMPLETED}
    ).sort(-Lesson.completed_at).limit(20).to_list()

    scenario_slugs = {l.scenario_slug for l in recent_lessons if l.scenario_slug}
    scenarios_list = await CurriculumScenario.find(
        {"slug": {"$in": list(scenario_slugs)}}
    ).to_list() if scenario_slugs else []
    scenario_labels = {s.slug: s.label for s in scenarios_list}

    lesson_history = [
        {
            "lesson": lesson,
            "scenario_label": scenario_labels.get(lesson.scenario_slug, ""),
        }
        for lesson in recent_lessons
    ]

    return templates.TemplateResponse(
        request=request,
        name="profilo.html",
        context={
            "profile": profile,
            "grammar_by_level": grammar_by_level,
            "cf_by_level": cf_by_level,
            "cefr_order": CEFR_ORDER,
            "scenario_map": scenario_map,
            "lesson_history": lesson_history,
            "weaknesses": weaknesses,
            "total_lessons": total_lessons,
            "vocab_known": vocab_known,
            "top_cf_labels": top_cf_labels,
        },
    )


@router.post("/profilo/persona")
async def save_profilo_persona(
    request: Request,
    student: Student = Depends(get_current_student),
    tags: Annotated[str, Form()] = "",
):
    profile = await get_or_create_profile(student.id)
    profile.persona.tags = [t.strip() for t in tags.split(",") if t.strip()]
    await profile.save()
    return RedirectResponse(url="/profilo?saved=1", status_code=303)
