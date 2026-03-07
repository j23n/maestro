"""
Per-student learning profile access.

Every function requires a student_id to scope queries.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from beanie import PydanticObjectId
from maestro.models import LearningProfile

if TYPE_CHECKING:
    from maestro.models import Student


async def get_profile(student_id: PydanticObjectId) -> LearningProfile | None:
    """Return the LearningProfile for a student, or None if not yet created."""
    return await LearningProfile.find_one({"student_id": student_id})


async def get_or_create_profile(student_id: PydanticObjectId) -> LearningProfile:
    """Return the LearningProfile for a student, creating an empty one if needed."""
    profile = await LearningProfile.find_one({"student_id": student_id})
    if profile is None:
        profile = LearningProfile(student_id=student_id)
        await profile.insert()
    return profile


async def get_cefr_level(student_id: PydanticObjectId) -> str:
    """Return the student's current CEFR estimate, defaulting to 'A0'."""
    profile = await get_profile(student_id)
    return profile.cefr_estimate if profile else "A0"


async def save_onboarding_field(
    student: Student, profile_field: str, answer: str
) -> None:
    """Save an onboarding answer to the appropriate student/profile field."""
    if not answer.strip():
        return

    answer = answer.strip()

    if profile_field == "name":
        student.name = answer[:30]
        await student.save()
    elif profile_field == "persona_tags":
        profile = await get_or_create_profile(student.id)
        new_tags = [t.strip() for t in answer.split(",") if t.strip()]
        profile.persona.tags = list(set(profile.persona.tags + new_tags))
        await profile.save()
    elif profile_field == "interests":
        profile = await get_or_create_profile(student.id)
        new_interests = [t.strip() for t in answer.split(",") if t.strip()]
        profile.persona.interests = list(set(profile.persona.interests + new_interests))
        await profile.save()
    elif profile_field == "background":
        profile = await get_or_create_profile(student.id)
        profile.persona.background = answer
        await profile.save()
    elif profile_field == "goal":
        profile = await get_or_create_profile(student.id)
        profile.persona.goal = answer
        await profile.save()
