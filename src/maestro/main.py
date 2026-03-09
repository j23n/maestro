from contextlib import asynccontextmanager
import datetime
import json
import logging

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
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
from maestro.session import clear_session_cookie, read_session
from maestro.templates import templates
from maestro.vocab.cache import ensure_loaded as load_vocab
from maestro.vocab.nlp import get_nlp
from maestro.routes import auth, vocab, profilo, grammar, lezione


# Capture the original extra= dict on every LogRecord so formatters read it directly
# without having to filter out built-in LogRecord attributes.
_orig_make_record = logging.Logger.makeRecord


def _patched_make_record(
    self, name, level, fn, lno, msg, args, exc_info, func=None, extra=None, sinfo=None
):
    rv = _orig_make_record(
        self, name, level, fn, lno, msg, args, exc_info, func, extra, sinfo
    )
    rv._extra = extra or {}
    return rv


logging.Logger.makeRecord = _patched_make_record


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "timestamp": datetime.datetime.fromtimestamp(
                record.created, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            **getattr(record, "_extra", {}),
        }
        if record.exc_info:
            obj["exc_info"] = record.exc_text or self.formatException(record.exc_info)
        if record.stack_info:
            obj["stack_info"] = record.stack_info
        return json.dumps(obj)


class _DevFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.levelname:<8} {record.name}: {record.getMessage()}"
        extra = getattr(record, "_extra", {})
        if extra:
            base += " | " + " ".join(f"{k}={v}" for k, v in extra.items())
        return base


def _setup_logging() -> logging.Handler:
    handler = logging.StreamHandler()
    if settings.ENVIRONMENT == "production":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(_DevFormatter())
    logging.root.setLevel(logging.WARNING)
    logging.root.handlers.clear()
    logging.root.addHandler(handler)
    logging.getLogger("maestro").setLevel(
        logging.DEBUG if settings.ENVIRONMENT == "development" else logging.INFO
    )
    return handler


_log_handler = _setup_logging()

logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        enable_logs=True,
    )
    logger.info("Sentry enabled (environment=%s)", settings.ENVIRONMENT)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Reconfigure uvicorn loggers to use our handler so access logs are structured
    for _name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        _lg = logging.getLogger(_name)
        _lg.handlers = [_log_handler]
        _lg.propagate = False
    logger.info("startup: connecting to database")
    await init_db()
    await seed_if_empty(get_db())
    logger.info("startup: loading NLP model")
    get_nlp()  # warm up spaCy model
    await load_vocab()
    logger.info("startup complete")
    yield
    logger.info("shutdown")


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(CSRFMiddleware, cookie_secure=settings.ENVIRONMENT == "production")
app.add_middleware(SlowAPIMiddleware)
app.mount("/static", StaticFiles(directory="src/maestro/static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/sentry-debug")
async def trigger_error():
    division_by_zero = 1 / 0  # noqa: F841


app.include_router(auth.router)
app.include_router(vocab.router)
app.include_router(profilo.router)
app.include_router(grammar.router)
app.include_router(lezione.router)


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
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
