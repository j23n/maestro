"""Regression tests for Jinja2 template escaping."""

import html
import json

import pytest
from jinja2 import Environment


@pytest.mark.unit
def test_tojson_forceescape_roundtrips():
    """Verify tojson | forceescape produces valid JSON after HTML-unescaping.

    Reproduces the bug from issue #165: without forceescape, double quotes in
    tojson output break the HTML attribute boundary.
    """
    env = Environment(autoescape=True)

    # Template mimics the pattern in lesson-activity-intro.html
    tpl = env.from_string(
        '<span data-tt-examples="{{ examples | tojson | forceescape }}">x</span>'
    )
    examples = ["das ist ein Hund.", 'sie sagt "Hallo"', "großartig!"]
    rendered = tpl.render(examples=examples)

    # The rendered HTML must not have raw double quotes inside the attribute
    # (other than the attribute delimiters themselves)
    attr_start = rendered.index('data-tt-examples="') + len('data-tt-examples="')
    attr_end = rendered.index('"', attr_start)
    attr_value = rendered[attr_start:attr_end]

    # attr_value should be HTML-escaped (no raw double quotes)
    assert '"' not in attr_value

    # Unescape and parse as JSON — must round-trip correctly
    unescaped = html.unescape(rendered[attr_start : rendered.index('">x', attr_start)])
    parsed = json.loads(unescaped)
    assert parsed == examples


@pytest.mark.unit
def test_tojson_without_forceescape_breaks():
    """Without forceescape, tojson Markup bypasses autoescape and breaks attributes."""
    env = Environment(autoescape=True)
    tpl = env.from_string('<span data-x="{{ items | tojson }}">x</span>')
    rendered = tpl.render(items=["a", "b"])

    # tojson returns Markup, so autoescape does NOT escape the double quotes
    # The attribute value will contain raw double quotes → broken HTML
    attr_start = rendered.index('data-x="') + len('data-x="')
    # Find the FIRST closing quote after attr_start — this will be the [ " from JSON
    attr_end = rendered.index('"', attr_start)
    attr_value = rendered[attr_start:attr_end]
    # The attribute value is truncated (just "[" instead of the full JSON)
    assert attr_value == "["
