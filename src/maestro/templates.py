import markdown
import random

from fastapi.templating import Jinja2Templates

from maestro.config import settings
from maestro.i18n import t as i18n_t

templates = Jinja2Templates(directory="templates")
templates.env.filters["markdown"] = lambda x: markdown.markdown(
    x, extensions=["extra", "nl2br", "sane_lists"]
)
templates.env.filters["shuffle"] = lambda lst: random.sample(lst, len(lst))
templates.env.globals["t"] = i18n_t
templates.env.globals["target_language"] = settings.TARGET_LANGUAGE_NAME


async def render_with_discover(
    request,
    name,
    context,
    *,
    student_id=None,
    status_code=200,
    should_hide_translations=False,
):
    """Render a Jinja template, then run vocab discover() on the full HTML."""
    from maestro.vocab.discover import discover, hide_translations

    response = templates.TemplateResponse(
        request=request, name=name, context=context, status_code=status_code
    )
    if student_id is not None:
        html = response.body.decode("utf-8")
        html = await discover(html, student_id=student_id)
        if should_hide_translations:
            html = hide_translations(html)
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
    return response
