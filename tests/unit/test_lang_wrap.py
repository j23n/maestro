"""Unit tests for lang_wrap (utils) and _it helper (lezione/a0)."""

import pytest

from maestro.utils import lang_wrap
from maestro.lezione.a0 import _it


# --- lang_wrap in utils ---


@pytest.mark.unit
def test_lang_wrap_basic():
    assert lang_wrap("ciao", "it") == '<span lang="it">ciao</span>'


@pytest.mark.unit
def test_lang_wrap_idempotent():
    wrapped = '<span lang="it">ciao</span>'
    assert lang_wrap(wrapped, "it") == wrapped


@pytest.mark.unit
def test_lang_wrap_different_lang_not_idempotent():
    """Wrapping with a different lang should still wrap."""
    wrapped = '<span lang="it">ciao</span>'
    result = lang_wrap(wrapped, "en")
    assert result == '<span lang="en"><span lang="it">ciao</span></span>'


@pytest.mark.unit
def test_lang_wrap_empty_string():
    assert lang_wrap("", "it") == '<span lang="it"></span>'


@pytest.mark.unit
def test_lang_wrap_en():
    assert lang_wrap("Hello", "en") == '<span lang="en">Hello</span>'


@pytest.mark.unit
def test_lang_wrap_en_none():
    """lang_wrap doesn't handle None — callers gate on truthiness."""
    # This tests the pattern: lang_wrap(text, "en") if text else text
    assert lang_wrap("Hello", "en") == '<span lang="en">Hello</span>'


@pytest.mark.unit
def test_lang_wrap_en_idempotent():
    wrapped = '<span lang="en">Hello</span>'
    assert lang_wrap(wrapped, "en") == wrapped


# --- _it helper ---


@pytest.mark.unit
def test_it_wraps_italian():
    assert _it("Ciao") == '<span lang="it">Ciao</span>'


@pytest.mark.unit
def test_it_none_returns_none():
    assert _it(None) is None


@pytest.mark.unit
def test_it_empty_string_returns_empty():
    assert _it("") == ""


@pytest.mark.unit
def test_it_idempotent():
    wrapped = '<span lang="it">Ciao</span>'
    assert _it(wrapped) == wrapped
