from typing import Annotated

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from maestro.learning import grammar_cache
from maestro.auth import get_current_student
from maestro.models import (
    CurriculumScenario,
    Lesson,
    LessonStatus,
    ScenarioProgress,
    Student,
    UserVocabularyCard,
)
from maestro.learning.profile import get_profile, get_or_create_profile
from maestro.templates import render_with_discover
from maestro.utils import CEFR_ORDER
from maestro.lessons.curriculum import (
    get_current_phase,
    get_unlocked_gps,
    PHASE_GATE_THRESHOLD,
)
from maestro.learning.weakness import (
    build_gp_titles,
    build_grammar_by_level,
    top_weaknesses,
)

router = APIRouter()

_PHASE_TITLES = {1: "percorso_phase_1", 2: "percorso_phase_2", 3: "percorso_phase_3"}


def _gp_status(code, unlocked_gps, introduced_set, mastered_set):
    if code in mastered_set:
        return "mastered"
    if code in introduced_set:
        return "introduced"
    if code in unlocked_gps:
        return "unlocked"
    return "locked"


def _build_percorso(
    profile, cefr, grammar_points, grammar_by_level, scenarios_by_level
):
    """Build the percorso (skill tree) data structure for A1+ students."""
    current_scenarios = scenarios_by_level.get(cefr, [])
    if not current_scenarios:
        return None

    current_phase = get_current_phase(profile, current_scenarios)
    lp = profile.active_progress if profile else None
    progress = lp.scenario_progress if lp else {}
    _no_progress = ScenarioProgress()

    # GP status sets
    level_gps = [gp for gp in grammar_points if gp.cefr_level == cefr]
    gp_by_code = {gp.code: gp for gp in level_gps}
    prereqs_map = {gp.code: gp.prerequisites for gp in level_gps if gp.prerequisites}
    all_gp_codes = {gp.code for gp in level_gps}
    unlocked_gps = get_unlocked_gps(profile, all_gp_codes, prereqs_map)
    introduced_set = set(lp.grammar_introduced) if lp else set()
    mastered_set = {
        s["point"].code for s in grammar_by_level.get(cefr, []) if s["mastered"]
    }

    # Group scenarios by phase
    by_phase: dict[int, list] = {1: [], 2: [], 3: []}
    for s in current_scenarios:
        by_phase.setdefault(s.phase, []).append(s)

    phases = []
    for phase_num in (1, 2, 3):
        phase_scenarios = by_phase.get(phase_num, [])
        completion_count = sum(
            1 for s in phase_scenarios if progress.get(s.slug, _no_progress).depth >= 1
        )
        if phase_num < current_phase:
            status = "completed"
        elif phase_num == current_phase:
            status = "current"
        else:
            status = "locked"

        scenario_items = []
        for s in phase_scenarios:
            sp = progress.get(s.slug, _no_progress)
            gp_statuses = []
            for code in s.gp_codes:
                gp = gp_by_code.get(code)
                if gp:
                    gp_statuses.append(
                        {
                            "code": code,
                            "label": gp.label,
                            "status": _gp_status(
                                code, unlocked_gps, introduced_set, mastered_set
                            ),
                        }
                    )
            scenario_items.append(
                {
                    "scenario": s,
                    "depth_completed": sp.depth,
                    "max_depth": len(s.depths),
                    "lesson_count": sp.lesson_count,
                    "gp_statuses": gp_statuses,
                }
            )

        phases.append(
            {
                "number": phase_num,
                "title_key": _PHASE_TITLES[phase_num],
                "status": status,
                "completion_count": completion_count,
                "total": len(phase_scenarios),
                "scenarios": scenario_items,
            }
        )

    # GP DAG: nodes grouped by category
    categories_seen = []
    gp_nodes_by_cat: dict[str, list] = {}
    for gp in level_gps:
        cat = gp.category or "other"
        if cat not in gp_nodes_by_cat:
            categories_seen.append(cat)
            gp_nodes_by_cat[cat] = []
        prereq_labels = []
        for p in gp.prerequisites:
            pgp = gp_by_code.get(p)
            prereq_labels.append({"code": p, "label": pgp.label if pgp else p})
        gp_nodes_by_cat[cat].append(
            {
                "code": gp.code,
                "label": gp.label,
                "status": _gp_status(
                    gp.code, unlocked_gps, introduced_set, mastered_set
                ),
                "prereqs": prereq_labels,
            }
        )

    gp_dag = [
        {"category": cat, "nodes": gp_nodes_by_cat[cat]} for cat in categories_seen
    ]

    return {
        "current_phase": current_phase,
        "phase_gate_threshold": PHASE_GATE_THRESHOLD,
        "phases": phases,
        "gp_dag": gp_dag,
    }


def _build_cf_by_level(comm_functions, profile):
    cf_by_level = {}
    for level in CEFR_ORDER:
        cfs = [cf for cf in comm_functions if cf.cefr_level == level]
        items = []
        for cf in cfs:
            count = (
                profile.active_progress.functions_counts.get(cf.code, 0)
                if profile
                else 0
            )
            items.append({"cf": cf, "count": count, "demonstrated": count >= 3})
        cf_by_level[level] = items
    return cf_by_level


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request, student: Student = Depends(get_current_student)
):
    profile = await get_profile(student.id)
    lang = request.state.lang_ctx.code
    await grammar_cache.ensure_loaded(lang)
    grammar_points = grammar_cache.grammar_points(lang)
    comm_functions = grammar_cache.comm_functions(lang)

    cefr = profile.active_progress.cefr_estimate if profile else "A0"
    gp_titles = build_gp_titles(grammar_points, cefr, lang)
    grammar_by_level = build_grammar_by_level(grammar_points, profile, gp_titles)
    cf_by_level = _build_cf_by_level(comm_functions, profile)

    # Top weaknesses for the summary
    weaknesses = top_weaknesses(grammar_by_level, cefr)

    # Profile summary stats
    total_lessons = await Lesson.find(
        {"student_id": student.id, "status": LessonStatus.COMPLETED}
    ).count()
    vocab_known = await UserVocabularyCard.find(
        {
            "student_id": student.id,
            "language": lang,
            "interval": {"$gte": 14},
            "excluded": {"$ne": True},
        }
    ).count()

    # Top communicative functions
    top_cf_labels = []
    if profile:
        cf_by_code = {cf.code: cf for cf in comm_functions}
        top_cfs = sorted(
            profile.active_progress.functions_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:3]
        top_cf_labels = [
            cf_by_code[code].label for code, _ in top_cfs if code in cf_by_code
        ]

    # Fetch all scenarios up to the current level in one query
    current_idx = CEFR_ORDER.index(cefr) if cefr in CEFR_ORDER else 0
    all_scenarios = await CurriculumScenario.find(
        {"cefr_level": {"$in": CEFR_ORDER[: current_idx + 1]}, "language": lang}
    ).to_list()

    # Partition by level and sort
    scenarios_by_level: dict[str, list[CurriculumScenario]] = {}
    for s in all_scenarios:
        scenarios_by_level.setdefault(s.cefr_level, []).append(s)
    for level, level_scenarios in scenarios_by_level.items():
        if level == "A0":
            level_scenarios.sort(key=lambda s: s.sequence or 0)
        else:
            level_scenarios.sort(key=lambda s: s.label)

    # Current-level scenario map
    progress = profile.active_progress.scenario_progress if profile else {}
    _no_progress = ScenarioProgress()
    scenario_map = [
        {
            "scenario": s,
            "depth_completed": progress.get(s.slug, _no_progress).depth,
            "lesson_count": progress.get(s.slug, _no_progress).lesson_count,
            "last_visited": progress.get(s.slug, _no_progress).last_visited,
        }
        for s in scenarios_by_level.get(cefr, [])
    ]

    # Completed-level scenario maps
    completed_levels = CEFR_ORDER[:current_idx]
    completed_scenario_maps = []
    for level in completed_levels:
        level_map = [
            {
                "scenario": s,
                "depth_completed": progress.get(s.slug, _no_progress).depth,
                "lesson_count": progress.get(s.slug, _no_progress).lesson_count,
            }
            for s in scenarios_by_level.get(level, [])
        ]
        if level_map:
            completed_scenario_maps.append((level, level_map))

    # Lesson history
    recent_lessons = (
        await Lesson.find({"student_id": student.id, "status": LessonStatus.COMPLETED})
        .sort(-Lesson.completed_at)
        .limit(20)
        .to_list()
    )

    # Build scenario labels from already-fetched scenarios
    scenario_labels = {s.slug: s.label for s in all_scenarios}
    # Fetch any slugs from lessons not covered by the level-based query
    missing_slugs = {
        lesson.scenario_slug
        for lesson in recent_lessons
        if lesson.scenario_slug and lesson.scenario_slug not in scenario_labels
    }
    if missing_slugs:
        extra = await CurriculumScenario.find(
            {"slug": {"$in": list(missing_slugs)}, "language": lang}
        ).to_list()
        for s in extra:
            scenario_labels[s.slug] = s.label

    lesson_history = [
        {
            "lesson": lesson,
            "scenario_label": scenario_labels.get(lesson.scenario_slug, ""),
        }
        for lesson in recent_lessons
    ]

    # Skill tree (A1+ only)
    percorso = None
    if cefr != "A0":
        percorso = _build_percorso(
            profile, cefr, grammar_points, grammar_by_level, scenarios_by_level
        )

    return await render_with_discover(
        request,
        "profile.html",
        {
            "profile": profile,
            "cefr": cefr,
            "cefr_idx": current_idx,
            "grammar_by_level": grammar_by_level,
            "cf_by_level": cf_by_level,
            "cefr_order": CEFR_ORDER,
            "scenario_map": scenario_map,
            "completed_scenario_maps": completed_scenario_maps,
            "lesson_history": lesson_history,
            "weaknesses": weaknesses,
            "total_lessons": total_lessons,
            "vocab_known": vocab_known,
            "top_cf_labels": top_cf_labels,
            "percorso": percorso,
        },
        student_id=student.id,
        create_cards=False,
    )


@router.post("/profile/persona")
async def save_profile_persona(
    request: Request,
    student: Student = Depends(get_current_student),
    background: Annotated[str, Form()] = "",
    interests: Annotated[str, Form()] = "",
    goal: Annotated[str, Form()] = "",
):
    profile = await get_or_create_profile(student.id)
    profile.persona.background = background.strip()
    profile.persona.interests = interests.strip()
    profile.persona.goal = goal.strip()
    await profile.save()
    return RedirectResponse(url="/profile?saved=1", status_code=303)
