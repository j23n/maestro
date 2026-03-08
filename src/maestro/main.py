from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi.middleware import SlowAPIMiddleware

from maestro.auth import RedirectToLogin, get_current_student
from maestro.config import settings
from maestro.csrf import CSRFMiddleware
from maestro.db import init_db
from maestro.i18n import t as i18n_t
from maestro.rate_limit import limiter
from maestro.session import clear_session_cookie
from maestro.templates import templates
from maestro.vocab.cache import ensure_loaded as load_vocab
from maestro.vocab.nlp import get_nlp
from maestro.routes import auth, vocab, profilo, grammar, lezione

logging.basicConfig(level=logging.WARNING)
_log_level = logging.DEBUG if settings.ENVIRONMENT == "development" else logging.INFO
logging.getLogger("maestro").setLevel(_log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    get_nlp()        # warm up spaCy model
    await load_vocab()
    yield


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(CSRFMiddleware, cookie_secure=settings.ENVIRONMENT == "production")
app.add_middleware(SlowAPIMiddleware)
app.mount("/static", StaticFiles(directory="src/maestro/static"), name="static")
app.include_router(auth.router)
app.include_router(vocab.router)
app.include_router(profilo.router)
app.include_router(grammar.router)
app.include_router(lezione.router)


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    from maestro.session import read_session
    if read_session(request):
        return RedirectResponse(url="/lezione/")
    return templates.TemplateResponse(request=request, name="landing.html")


@app.exception_handler(RedirectToLogin)
async def redirect_to_login(request: Request, exc: RedirectToLogin):
    response = RedirectResponse(url="/auth/login")
    if exc.clear_cookie:
        clear_session_cookie(response)
    return response


async def _render_error(request: Request, code: int, message_key: str):
    try:
        await get_current_student(request)
    except RedirectToLogin:
        pass
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"code": code, "message": i18n_t(message_key)},
        status_code=code,
    )


@app.exception_handler(429)
async def rate_limit_exceeded(request: Request, exc):
    msg = i18n_t("error_429")
    headers = {"Retry-After": "60"}
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            f'<p class="error">{msg}</p>',
            status_code=429,
            headers=headers,
        )
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"code": 429, "message": msg},
        status_code=429,
        headers=headers,
    )


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return await _render_error(request, 404, "error_404")


@app.exception_handler(403)
async def forbidden(request: Request, exc):
    return await _render_error(request, 403, "error_403")
