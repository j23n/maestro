import markdown
import random
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")
templates.env.filters["markdown"] = lambda x: markdown.markdown(
    x, extensions=["extra", "nl2br", "sane_lists"]
)
templates.env.filters["shuffle"] = lambda lst: random.sample(lst, len(lst))
