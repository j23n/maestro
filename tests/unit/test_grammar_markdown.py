"""Tests for preprocess_grammar_markdown — LLM span-tag fixups before markdown rendering.

To add a new case: paste the raw LLM explanation string as `raw`, and the expected
markdown tokens you want to see in the output (e.g. heading text, table row, etc.).
"""

from maestro.vocab.discover import preprocess_grammar_markdown


# ---------------------------------------------------------------------------
# Heading fixups
# ---------------------------------------------------------------------------


def test_heading_in_span_basic():
    """## heading wrapped in a single span is extracted."""
    raw = '<span lang="en">## Why this matters</span>\n\nSome text.'
    result = preprocess_grammar_markdown(raw)
    assert result.startswith("## Why this matters")


def test_heading_in_span_with_trailing_newlines():
    """Trailing \\n\\n inside the span are preserved so the heading is a separate block."""
    raw = '<span lang="en">## Why this matters\n\n</span><span lang="en">Body text.</span>'
    result = preprocess_grammar_markdown(raw)
    assert "## Why this matters\n\n" in result
    # Body text must NOT be inside the heading
    assert result.index("## Why this matters") < result.index("Body text.")


def test_heading_h3_in_span():
    raw = '<span lang="it">### Formazione\n\n</span><span lang="it">Il verbo.</span>'
    result = preprocess_grammar_markdown(raw)
    assert result.startswith("### Formazione")


def test_heading_not_mangled_when_no_span():
    """Headings that are already bare should pass through unchanged."""
    raw = "## Why this matters\n\nBody text."
    result = preprocess_grammar_markdown(raw)
    assert result == raw


def test_heading_span_does_not_strip_body_spans():
    """Span tags on non-heading lines must be left intact."""
    raw = (
        '<span lang="en">## Section\n\n</span>'
        '<span lang="en">Normal</span> <span lang="it">testo</span>.'
    )
    result = preprocess_grammar_markdown(raw)
    assert '<span lang="en">Normal</span>' in result
    assert '<span lang="it">testo</span>' in result


# ---------------------------------------------------------------------------
# Table fixups
# ---------------------------------------------------------------------------


def test_table_with_leading_span_on_header_row():
    """Leading <span> before | is stripped so the parser sees the table."""
    raw = '<span lang="en">| Singular | Plural |\n|---|---|\n| libro | libri |\n</span>'
    result = preprocess_grammar_markdown(raw)
    assert result.startswith("| Singular | Plural |")


def test_table_row_spans_stripped():
    """All span tags inside table rows are removed."""
    raw = (
        "| | Masculine | Feminine |\n"
        "|---|---|---|\n"
        '| **Singular** | <span lang="it">quanto</span> | <span lang="it">quanta</span> |\n'
        '| **Plural** | <span lang="it">quanti</span> | <span lang="it">quante</span> |\n'
    )
    result = preprocess_grammar_markdown(raw)
    assert "<span" not in result
    assert "| **Singular** | quanto | quanta |" in result


def test_table_mixed_span_wrapping():
    """Real-world pattern from inter_che: header row inside span, cells span across."""
    raw = (
        '<span lang="en">| | Masculine | Feminine |\n'
        "|---|---|---|\n"
        '| **Singular** | </span><span lang="it">quanto</span><span lang="en"> | </span><span lang="it">quanta</span><span lang="en"> |\n'
        '| **Plural** | </span><span lang="it">quanti</span><span lang="en"> | </span><span lang="it">quante</span><span lang="en"> |\n'
        "</span>"
    )
    result = preprocess_grammar_markdown(raw)
    assert result.startswith("| | Masculine | Feminine |")
    assert "| **Singular** | quanto | quanta |" in result
    assert "| **Plural** | quanti | quante |" in result
    assert "<span" not in "\n".join(
        line for line in result.splitlines() if line.strip().startswith("|")
    )


def test_table_with_closing_span_before_pipe():
    """Real-world: </span><span lang="en">| col | — closing span before pipe must also be stripped."""
    raw = (
        '</span><span lang="en">| | Masculine | Feminine |\n'
        "|---|---|---|\n"
        "| **Singular** | quanto | quanta |\n"
    )
    result = preprocess_grammar_markdown(raw)
    assert result.startswith("| | Masculine | Feminine |")
    assert "<span" not in "\n".join(
        line for line in result.splitlines() if line.strip().startswith("|")
    )


def test_non_table_lines_untouched():
    """Lines that don't start with | keep their spans."""
    raw = '<span lang="en">Some sentence with </span><span lang="it">una parola</span>.'
    result = preprocess_grammar_markdown(raw)
    assert result == raw


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------


def test_heading_and_table_together():
    """Both fixes applied in the same document."""
    raw = (
        '<span lang="en">## Forms\n\n</span>'
        '<span lang="en">| Sing | Plur |\n'
        "|---|---|\n"
        "| libro | libri |\n"
        "</span>"
    )
    result = preprocess_grammar_markdown(raw)
    assert result.startswith("## Forms\n\n")
    assert "| Sing | Plur |" in result
    assert "<span" not in "\n".join(
        line for line in result.splitlines() if line.strip().startswith("|")
    )
