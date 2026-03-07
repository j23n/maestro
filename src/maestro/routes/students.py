from beanie import PydanticObjectId
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from maestro.models import Student, LearningProfile
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
async def students_create(request: Request):
    student = Student()
    await student.insert()
    response = RedirectResponse(url="/lezione/", status_code=303)
    response.set_cookie("student_id", str(student.id), max_age=365 * 24 * 3600)
    return response


@router.delete("/students/{student_id}", response_class=HTMLResponse)
async def students_delete(student_id: str, request: Request):
    student = await Student.get(PydanticObjectId(student_id))
    if not student:
        raise HTTPException(status_code=404)
    await student.delete()
    profile = await LearningProfile.find_one({"student_id": student.id})
    if profile:
        await profile.delete()
    response = HTMLResponse(status_code=200)
    if request.cookies.get("student_id") == student_id:
        response.delete_cookie("student_id")
    return response


@router.post("/students/{student_id}/select", response_class=HTMLResponse)
async def students_select(student_id: str):
    response = RedirectResponse(url="/lezione/", status_code=303)
    response.set_cookie("student_id", student_id, max_age=365 * 24 * 3600)
    return response
