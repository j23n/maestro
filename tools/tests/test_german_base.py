"""The German grammar base (content/de/grammar/base.yaml) and its topic pages."""

import os

from maestro_content import grammar

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GRAMMAR = os.path.join(ROOT, "content", "de", "grammar")


def test_base_names_only_pages_that_exist():
    topics = grammar.load_all(GRAMMAR)
    points = grammar.load_base(os.path.join(GRAMMAR, "base.yaml"))
    assert len(points) == 209
    assert grammar.check_base(points, topics) == []
    assert {t.id for t in topics} <= {p.topic for p in points if p.topic}, "every page covers a point"
    assert all(t.summary and t.body for t in topics)
