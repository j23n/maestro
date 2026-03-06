from typing import Annotated

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from maestro.models import Student
from maestro.templates import templates

router = APIRouter()


@router.get("/students/", response_class=HTMLResponse)
async def students_page(request: Request):
    students = await Student.find_all().sort(Student.created_at).to_list()
    return templates.TemplateResponse(
        request=request,
        name="students.html",
        context={"students": students},
    )


@router.post("/students/", response_class=HTMLResponse)
async def students_create(
    request: Request,
    name: Annotated[str, Form()],
):
    name = name.strip()
    if not name:
        return RedirectResponse(url="/students/", status_code=303)
    student = Student(name=name)
    await student.insert()
    response = RedirectResponse(url="/lezione/", status_code=303)
    response.set_cookie("student_id", str(student.id), max_age=365 * 24 * 3600)
    return response


@router.post("/students/{student_id}/select", response_class=HTMLResponse)
async def students_select(student_id: str):
    response = RedirectResponse(url="/lezione/", status_code=303)
    response.set_cookie("student_id", student_id, max_age=365 * 24 * 3600)
    return response
