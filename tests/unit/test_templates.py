import pytest
from markupsafe import Markup

from maestro.templates import templates


@pytest.mark.unit
def test_lang_it_filter():
    """The lang_it filter wraps text in <span lang="it">."""
    result = templates.env.filters["lang_it"]("ciao")
    assert result == Markup('<span lang="it">ciao</span>')


@pytest.mark.unit
def test_lang_it_filter_escapes_html():
    """The lang_it filter should not double-escape already-safe Markup."""
    safe = Markup("già")
    result = templates.env.filters["lang_it"](safe)
    assert result == Markup('<span lang="it">già</span>')
