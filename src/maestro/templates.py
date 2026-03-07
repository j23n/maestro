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
