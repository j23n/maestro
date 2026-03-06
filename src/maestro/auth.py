from fastapi import Request
from beanie import PydanticObjectId
from maestro.models import Student


class RedirectToStudents(Exception):
    pass


async def get_current_student(request: Request) -> Student:
    """Extract student from cookie, or raise redirect to student picker."""
    raw = request.cookies.get("student_id")
    if not raw:
        raise RedirectToStudents()
    try:
        student = await Student.get(PydanticObjectId(raw))
    except Exception:
        student = None
    if student is None:
        raise RedirectToStudents()
    request.state.student = student
    return student
