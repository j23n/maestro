from contextlib import asynccontextmanager
import logging

logging.basicConfig(level=logging.WARNING)
logging.getLogger("maestro").setLevel(logging.DEBUG)

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from maestro.auth import RedirectToStudents, get_current_student
from maestro.db import init_db
from maestro.i18n import t as i18n_t
from maestro.templates import templates
from maestro.vocab.cache import ensure_loaded as load_vocab
from maestro.vocab.nlp import get_nlp
from maestro.routes import auth, vocab, profilo, grammar, lezione, students


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    get_nlp()        # warm up spaCy model
    await load_vocab()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="src/maestro/static"), name="static")
app.include_router(auth.router)
app.include_router(students.router)
app.include_router(vocab.router)
app.include_router(profilo.router)
app.include_router(grammar.router)
app.include_router(lezione.router)


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    if request.cookies.get("student_id"):
        return RedirectResponse(url="/lezione/")
    return templates.TemplateResponse(request=request, name="landing.html")


@app.exception_handler(RedirectToStudents)
async def redirect_to_students(request: Request, exc: RedirectToStudents):
    return RedirectResponse(url="/students/")


async def _render_error(request: Request, code: int, message_key: str):
    try:
        await get_current_student(request)
    except RedirectToStudents:
        pass
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"code": code, "message": i18n_t(message_key)},
        status_code=code,
    )


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return await _render_error(request, 404, "error_404")


@app.exception_handler(403)
async def forbidden(request: Request, exc):
    return await _render_error(request, 403, "error_403")
