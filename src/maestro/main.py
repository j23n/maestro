from contextlib import asynccontextmanager
import logging

logging.basicConfig(level=logging.WARNING)
logging.getLogger("maestro").setLevel(logging.DEBUG)

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from maestro.auth import RedirectToStudents
from maestro.db import init_db
from maestro.templates import templates
from maestro.vocab.cache import ensure_loaded as load_vocab
from maestro.vocab.nlp import get_nlp
from maestro.routes import vocab, profilo, grammar, lezione, students


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    get_nlp()        # warm up spaCy Italian model
    await load_vocab()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="src/maestro/static"), name="static")
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
