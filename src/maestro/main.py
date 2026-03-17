from contextlib import asynccontextmanager
import datetime
import json
import logging
from pathlib import Path

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi.middleware import SlowAPIMiddleware

from maestro.auth import RedirectToLogin, get_current_student
from maestro.config import settings
from maestro.csrf import CSRFMiddleware
from maestro.db import get_db, init_db
from maestro.learning.gp_sync import sync_if_changed as sync_grammar_points
from maestro.learning.vocab_sync import sync_if_changed as sync_a0_vocab
from maestro.migrations import run_pending
from maestro.seed import seed_if_empty
from maestro.i18n import t as i18n_t
from maestro.rate_limit import limiter
from maestro.session import clear_session_cookie, read_session
from maestro.templates import render_with_discover
from maestro.vocab.cache import ensure_loaded as load_vocab
from maestro.vocab.nlp import get_nlp
from maestro.routes import (
    admin,
    auth,
    vocab,
    profilo,
    grammar,
    lezione,
    feedback,
    legal,
    account,
)
from maestro import hints


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "timestamp": datetime.datetime.fromtimestamp(
                record.created, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname.lower(),
            "name": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "_extra", None)
        if extra:
            obj["extra"] = extra
        if record.exc_info:
            obj["exc_info"] = record.exc_text or self.formatException(record.exc_info)
        if record.stack_info:
            obj["stack_info"] = record.stack_info
        return json.dumps(obj)


class _DevFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.levelname:<8} {record.name}: {record.getMessage()}"
        extra = getattr(record, "_extra", None)
        if extra:
            base += " [" + ", ".join(f"{k}={v}" for k, v in extra.items()) + "]"
        if record.exc_info and record.exc_info[0] is not None:
            base += "\n" + self.formatException(record.exc_info)
        return base


def _setup_logging() -> logging.Handler:
    _orig_make_record = logging.Logger.makeRecord

    def _patched_make_record(
        self,
        name,
        level,
        fn,
        lno,
        msg,
        args,
        exc_info,
        func=None,
        extra=None,
        sinfo=None,
    ):
        rv = _orig_make_record(
            self, name, level, fn, lno, msg, args, exc_info, func, extra, sinfo
        )
        rv._extra = dict(extra) if extra else None
        return rv

    logging.Logger.makeRecord = _patched_make_record

    handler = logging.StreamHandler()
    if settings.ENVIRONMENT == "production":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(_DevFormatter())
    logging.root.setLevel(logging.WARNING)
    logging.root.handlers.clear()
    logging.root.addHandler(handler)

    app_logger = logging.getLogger("maestro")
    app_logger.setLevel(settings.LOG_LEVEL.upper())
    return handler


_log_handler = _setup_logging()

logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            LoggingIntegration(
                level=logging.DEBUG,
                event_level=logging.ERROR,
                sentry_logs_level=logging.DEBUG,
            ),
        ],
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
    await run_pending(get_db())
    await sync_grammar_points(get_db())
    await sync_a0_vocab(get_db())
    await seed_if_empty(get_db())
    logger.info("startup: loading NLP model")
    get_nlp()  # warm up spaCy model
    await load_vocab()
    logger.info("startup complete")
    yield
    logger.info("shutdown")
    from maestro.tts import _get_tts_client

    if _get_tts_client.cache_info().currsize:
        await _get_tts_client().aclose()

    from maestro.stt import _get_stt_client

    if _get_stt_client.cache_info().currsize:
        await _get_stt_client().aclose()


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(CSRFMiddleware, cookie_secure=settings.ENVIRONMENT == "production")
app.add_middleware(SlowAPIMiddleware)
if settings.DATA_DIR != settings.STATIC_DIR:
    Path(settings.DATA_DIR, "audio").mkdir(parents=True, exist_ok=True)
    app.mount(
        "/static/audio",
        StaticFiles(directory=Path(settings.DATA_DIR) / "audio"),
        name="audio",
    )
app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")


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
app.include_router(hints.router)
app.include_router(feedback.router)
app.include_router(legal.router)
app.include_router(account.router)
app.include_router(admin.router)


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    if read_session(request):
        return RedirectResponse(url="/lezione/")
    return await render_with_discover(
        request, "landing.html", {}, discover_anonymous=True
    )


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
    msg = i18n_t(message_key)
    sub_key = f"{message_key}_sub"
    sub = i18n_t(sub_key)
    # i18n returns the key itself when not found — treat as empty
    if sub == sub_key:
        sub = ""
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            f'<div class="generating-error-card" style="text-align:center;margin:2rem auto;max-width:400px;">'
            f'<p style="font-family:var(--f-serif);font-size:2rem;font-weight:700;'
            f'color:var(--c-border);margin:0 0 0.5rem;">{code}</p>'
            f'<p class="generating-title">{msg}</p>'
            f"</div>",
            status_code=code,
        )
    return await render_with_discover(
        request,
        "error.html",
        {"code": code, "message": msg, "subtitle": sub},
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
    response = await render_with_discover(
        request,
        "error.html",
        {"code": 429, "message": msg, "subtitle": ""},
        status_code=429,
    )
    response.headers["Retry-After"] = "60"
    return response


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return await _render_error(request, 404, "error_404")


@app.exception_handler(403)
async def forbidden(request: Request, exc):
    return await _render_error(request, 403, "error_403")


@app.exception_handler(500)
async def server_error(request: Request, exc: Exception):
    try:
        return await _render_error(request, 500, "error_500")
    except Exception:
        logger.exception("error handler itself failed")
        return HTMLResponse("Internal Server Error", status_code=500)
