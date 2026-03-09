from contextlib import asynccontextmanager
import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi.middleware import SlowAPIMiddleware

from maestro.auth import RedirectToLogin, get_current_student
from maestro.config import settings
from maestro.csrf import CSRFMiddleware
from maestro.db import get_db, init_db
from maestro.seed import seed_if_empty
from maestro.i18n import t as i18n_t
from maestro.rate_limit import limiter
from maestro.session import clear_session_cookie
from maestro.templates import templates
from maestro.vocab.cache import ensure_loaded as load_vocab
from maestro.vocab.nlp import get_nlp
from maestro.routes import auth, vocab, profilo, grammar, lezione


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            obj["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(obj)


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    if settings.ENVIRONMENT == "production":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
    logging.root.setLevel(logging.WARNING)
    logging.root.handlers = [handler]
    logging.getLogger("maestro").setLevel(
        logging.DEBUG if settings.ENVIRONMENT == "development" else logging.INFO
    )


_setup_logging()

_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import sentry_sdk

    if settings.SENTRY_DSN:
        sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.1)
        _log.info("Sentry enabled")

    _log.info("startup: connecting to database")
    await init_db()
    await seed_if_empty(get_db())
    _log.info("startup: loading NLP model")
    get_nlp()  # warm up spaCy model
    await load_vocab()
    _log.info("startup complete")
    yield
    _log.info("shutdown")


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(CSRFMiddleware, cookie_secure=settings.ENVIRONMENT == "production")
app.add_middleware(SlowAPIMiddleware)
app.mount("/static", StaticFiles(directory="src/maestro/static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


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
