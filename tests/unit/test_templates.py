import pytest
from markupsafe import Markup

from maestro.templates import templates


@pytest.mark.unit
def test_lang_it_filter():
    """The lang_it filter wraps text in <span lang="it">."""
    result = templates.env.filters["lang_it"]("ciao")
    assert result == Markup('<span lang="it">ciao</span>')


@pytest.mark.unit
def test_lang_it_filter_escapes_unsafe():
    """The lang_it filter escapes raw HTML to prevent XSS."""
    result = templates.env.filters["lang_it"]("<script>alert(1)</script>")
    assert "<script>" not in str(result)
    assert "&lt;script&gt;" in str(result)


@pytest.mark.unit
def test_lang_it_filter_none():
    """The lang_it filter returns empty Markup for None."""
    result = templates.env.filters["lang_it"](None)
    assert result == Markup("")
