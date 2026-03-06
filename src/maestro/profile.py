"""
Singleton learning profile access.

The app currently assumes a single student. All profile lookups go through
here so the assumption is easy to find and change later.
"""
from maestro.models import LearningProfile


async def get_profile() -> LearningProfile | None:
    """Return the singleton LearningProfile, or None if not yet created."""
    return await LearningProfile.find_one()


async def get_or_create_profile() -> LearningProfile:
    """Return the singleton LearningProfile, creating an empty one if needed."""
    profile = await LearningProfile.find_one()
    if profile is None:
        profile = LearningProfile()
        await profile.insert()
    return profile


async def get_cefr_level() -> str:
    """Return the student's current CEFR estimate, defaulting to 'A1'."""
    profile = await get_profile()
    return profile.cefr_estimate if profile else "A1"
