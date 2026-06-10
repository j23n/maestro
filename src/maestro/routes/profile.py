import math
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from maestro.learning import grammar_cache
from maestro.auth import get_current_student
from maestro.models import (
    CurriculumScenario,
    LearningProfile,
    Lesson,
    LessonStatus,
    ScenarioProgress,
    Student,
    UserVocabularyCard,
)
from maestro.learning.profile import get_profile, get_or_create_profile
from maestro.templates import render, render_with_discover
from maestro.utils import CEFR_ORDER, utcnow
from maestro.lessons.curriculum import (
    get_current_phase,
    get_unlocked_gps,
    PHASE_GATE_THRESHOLD,
)
from maestro.learning.mastery import CF_DEMONSTRATED_COUNT
from maestro.learning.weakness import (
    build_grammar_by_level,
    build_titles,
    top_weaknesses,
)

router = APIRouter()

_PHASE_TITLES = {1: "percorso_phase_1", 2: "percorso_phase_2", 3: "percorso_phase_3"}

_ALLOWED_OVERRIDE_LEVELS = ("A0", "A1", "A2")


def _gp_status(code, unlocked_gps, introduced_set, mastered_set):
    if code in mastered_set:
        return "mastered"
    if code in introduced_set:
        return "introduced"
    if code in unlocked_gps:
        return "unlocked"
    return "locked"


def _build_percorso(
    profile, cefr, grammar_points, grammar_by_level, scenarios_by_level, cf_items
):
    """Build the percorso (skill tree) data structure for A1+ students.

    `cf_items` is the current level's entries from _build_cf_by_level.
    Includes the graduation gates (>=90% GPs mastered and >=90% CFs
    demonstrated — see profile._compute_cefr), per-scenario coverage badges
    (how many gate gaps a scenario advances), and a deterministic
    "recommended next" scenario mirroring the coverage-driven selection
    scoring (lessons.selection.pick_scenario) without its jitter/cooldown.
    """
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
    demonstrated_set = {i["cf"].code for i in cf_items if i["demonstrated"]}
    all_cf_codes = {i["cf"].code for i in cf_items}

    # --- Graduation gates (the 90/90 requirement for the next level) ---
    gp_total = len(level_gps)
    cf_total = len(cf_items)
    gp_done = len(mastered_set & all_gp_codes)
    cf_done = len(demonstrated_set)
    next_idx = CEFR_ORDER.index(cefr) + 1 if cefr in CEFR_ORDER else 0
    gates = {
        "next_level": CEFR_ORDER[next_idx] if next_idx < len(CEFR_ORDER) else None,
        "gp_total": gp_total,
        "gp_done": gp_done,
        "gp_target": math.ceil(0.9 * gp_total),
        "gp_pct": round(100 * gp_done / gp_total) if gp_total else 0,
        "cf_total": cf_total,
        "cf_done": cf_done,
        "cf_target": math.ceil(0.9 * cf_total),
        "cf_pct": round(100 * cf_done / cf_total) if cf_total else 0,
    }

    # Group scenarios by phase
    by_phase: dict[int, list] = {1: [], 2: [], 3: []}
    for s in current_scenarios:
        by_phase.setdefault(s.phase, []).append(s)

    recommended_slug = None
    recommended_key = None

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
            # Coverage badges: gate gaps this scenario can advance
            known_gps = [c for c in s.gp_codes if c in gp_by_code]
            advances_gp = sum(1 for c in known_gps if c not in mastered_set)
            advances_cf = sum(
                1 for c in s.cf_codes if c in all_cf_codes and c not in demonstrated_set
            )
            scenario_items.append(
                {
                    "scenario": s,
                    "depth_completed": sp.depth,
                    "max_depth": len(s.depths),
                    "lesson_count": sp.lesson_count,
                    "gp_statuses": gp_statuses,
                    "advances_gp": advances_gp,
                    "advances_cf": advances_cf,
                }
            )

            # Recommended next: deterministic version of the planner's
            # coverage scoring (unmastered + introducible + 0.5*undemonstrated,
            # unvisited as tiebreaker) over the current phase only.
            if status == "current":
                introducible = sum(
                    1
                    for c in known_gps
                    if c not in mastered_set
                    and c not in introduced_set
                    and c in unlocked_gps
                )
                key = (
                    advances_gp + introducible + 0.5 * advances_cf,
                    1 if sp.depth == 0 else 0,
                    -sp.depth,
                    s.slug,  # stable tiebreak
                )
                if recommended_key is None or key > recommended_key:
                    recommended_key = key
                    recommended_slug = s.slug

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
        "gates": gates,
        "recommended_slug": recommended_slug,
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
            items.append(
                {
                    "cf": cf,
                    "count": count,
                    "demonstrated": count >= CF_DEMONSTRATED_COUNT,
                }
            )
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

    cefr = profile.active_progress.effective_cefr_level if profile else "A0"
    gp_titles = build_titles(grammar_points, cefr, lang)
    grammar_by_level = build_grammar_by_level(grammar_points, profile, gp_titles)
    cf_titles = build_titles(comm_functions, cefr, lang)
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
            profile,
            cefr,
            grammar_points,
            grammar_by_level,
            scenarios_by_level,
            cf_by_level.get(cefr, []),
        )

    cefr_estimate = profile.active_progress.cefr_estimate if profile else "A0"
    cefr_override = profile.active_progress.cefr_level_override if profile else None

    return await render_with_discover(
        request,
        "profile.html",
        {
            "profile": profile,
            "cefr": cefr,
            "cefr_estimate": cefr_estimate,
            "cefr_override": cefr_override,
            "cefr_override_options": list(_ALLOWED_OVERRIDE_LEVELS),
            "cefr_idx": current_idx,
            "grammar_by_level": grammar_by_level,
            "cf_by_level": cf_by_level,
            "cf_titles": cf_titles,
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


@router.post("/profile/level")
async def save_profile_level(
    request: Request,
    student: Student = Depends(get_current_student),
    level: Annotated[str, Form()] = "",
):
    if level not in _ALLOWED_OVERRIDE_LEVELS:
        return RedirectResponse(url="/profile#preferences", status_code=303)

    profile = await get_or_create_profile(student.id)
    lang = profile.target_language
    lp = profile.active_progress
    old_effective = lp.effective_cefr_level

    update_fields: dict = {f"progress.{lang}.cefr_level_override": level}
    # Picking A1+ marks A0 onboarding as done so auto-advancement isn't blocked
    # by the A0 graduation gate (which requires completing all A0 scenarios).
    if level != "A0" and not lp.onboarding_completed:
        update_fields[f"progress.{lang}.onboarding_completed"] = True

    await LearningProfile.get_pymongo_collection().update_one(
        {"_id": profile.id}, {"$set": update_fields}
    )

    profile = await get_or_create_profile(student.id)
    new_effective = profile.active_progress.effective_cefr_level

    if new_effective != old_effective:
        await Lesson.get_pymongo_collection().update_many(
            {
                "student_id": student.id,
                "language": lang,
                "status": {
                    "$in": [LessonStatus.ACTIVE.value, LessonStatus.PLANNING.value]
                },
            },
            {
                "$set": {
                    "status": LessonStatus.ABANDONED.value,
                    "generating": False,
                }
            },
        )

    return RedirectResponse(url="/profile?saved=1#tab-preferences", status_code=303)


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


_STORYLINE_MAX_LEN = 1500


@router.post("/profile/storyline")
async def save_profile_storyline(
    request: Request,
    student: Student = Depends(get_current_student),
    storyline: Annotated[str, Form()] = "",
):
    profile = await get_or_create_profile(student.id)
    lang = profile.target_language
    trimmed = storyline.strip()[:_STORYLINE_MAX_LEN]
    await LearningProfile.get_pymongo_collection().update_one(
        {"_id": profile.id},
        {
            "$set": {
                f"progress.{lang}.storyline": trimmed,
                f"progress.{lang}.storyline_updated_at": utcnow(),
            }
        },
    )
    return RedirectResponse(url="/profile?saved=1#tab-preferences", status_code=303)


@router.post("/profile/storyline/regenerate", response_class=HTMLResponse)
async def regenerate_profile_storyline(
    request: Request,
    student: Student = Depends(get_current_student),
):
    from maestro.lessons.storyline import evolve_storyline, _fetch_recent_completed

    profile = await get_or_create_profile(student.id)
    lang = profile.target_language
    lp = profile.active_progress
    old = lp.storyline if lp else ""

    recent = await _fetch_recent_completed(student.id, lang, limit=5)
    new_text = await evolve_storyline(
        old_storyline=old,
        persona=profile.persona,
        recent_lessons=recent,
        language=lang,
        student_id=student.id,
        profile_id=profile.id,
    )

    if new_text and new_text != old:
        await LearningProfile.get_pymongo_collection().update_one(
            {"_id": profile.id},
            {
                "$set": {
                    f"progress.{lang}.storyline": new_text,
                    f"progress.{lang}.storyline_updated_at": utcnow(),
                    f"progress.{lang}.storyline_lessons_since_evolve": 0,
                }
            },
        )

    return render(
        request,
        "partials/storyline-textarea.html",
        {"storyline": new_text or old},
    )
