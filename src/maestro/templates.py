import markdown
import random
import re

from fastapi.templating import Jinja2Templates

from maestro.i18n import t as i18n_t
from maestro.language import DEFAULT_LANGUAGE, get_language_config

_TRANSLATION_RE = re.compile(r"(</span>)\s*\(([^)]+)\)")


def _hide_translations(html: str) -> str:
    """Wrap parenthesized English translations after </span> in a toggleable span.

    Used as a Jinja filter in reading/listening templates.
    """
    return _TRANSLATION_RE.sub(r'\1 <span class="translation-toggle">\2</span>', html)


_templates = Jinja2Templates(directory="templates")
_templates.env.filters["markdown"] = lambda x: markdown.markdown(
    x, extensions=["extra", "nl2br", "sane_lists"]
)
_templates.env.filters["shuffle"] = lambda lst: random.sample(lst, len(lst))
_templates.env.filters["hide_translations"] = _hide_translations
_templates.env.globals["t"] = i18n_t
_default_cfg = get_language_config(DEFAULT_LANGUAGE)
_templates.env.globals["target_language"] = _default_cfg.name
_templates.env.globals["target_language_code"] = _default_cfg.code


def _inject_language(request, context: dict) -> dict:
    """Override target_language/target_language_code from per-student lang_ctx."""
    lang_ctx = getattr(getattr(request, "state", None), "lang_ctx", None)
    if lang_ctx is not None:
        context.setdefault("target_language", lang_ctx.name)
        context.setdefault("target_language_code", lang_ctx.code)
    return context


def render(request, name, context, *, status_code=200):
    """Render a Jinja template without vocab discovery."""
    return _templates.TemplateResponse(
        request=request,
        name=name,
        context=_inject_language(request, context),
        status_code=status_code,
    )


async def render_with_discover(
    request,
    name,
    context,
    *,
    student_id=None,
    status_code=200,
    create_cards=False,
    discover_anonymous=False,
):
    """Render a Jinja template, then run vocab discover() on the full HTML."""
    from maestro.vocab.discover import discover

    response = _templates.TemplateResponse(
        request=request,
        name=name,
        context=_inject_language(request, context),
        status_code=status_code,
    )
    if student_id is not None or discover_anonymous:
        lang_ctx = getattr(getattr(request, "state", None), "lang_ctx", None)
        html = response.body.decode("utf-8")
        html = await discover(
            html,
            student_id=student_id,
            create_cards=student_id is not None and create_cards,
            language=lang_ctx.code if lang_ctx else None,
        )
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
    return response
