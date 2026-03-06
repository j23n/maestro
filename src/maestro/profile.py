"""
Per-student learning profile access.

Every function requires a student_id to scope queries.
"""
from beanie import PydanticObjectId
from maestro.models import LearningProfile


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
