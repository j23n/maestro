import markdown
import random

from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from maestro.config import settings
from maestro.i18n import t as i18n_t

templates = Jinja2Templates(directory="templates")
templates.env.filters["markdown"] = lambda x: markdown.markdown(
    x, extensions=["extra", "nl2br", "sane_lists"]
)
templates.env.filters["shuffle"] = lambda lst: random.sample(lst, len(lst))
templates.env.filters["lang_it"] = lambda text: Markup(f'<span lang="it">{text}</span>')
templates.env.globals["t"] = i18n_t
templates.env.globals["target_language"] = settings.TARGET_LANGUAGE_NAME


async def render_with_discover(request, name, context, student_id=None):
    """Render a Jinja template, then run vocab discover() on the full HTML."""
    from maestro.vocab.discover import discover

    template = templates.get_template(name)
    html = template.render({"request": request, **context})
    if student_id is not None:
        html = await discover(html, student_id=student_id)
    return HTMLResponse(html)
