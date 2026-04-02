"""Integration tests for DWDS parser using cached real HTML responses.

These tests verify that parse_html() correctly extracts POS and senses from
actual DWDS pages for German A0 words that were previously broken (particles,
pronouns, etc.).

Fixtures in tests/fixtures/dwds/ were captured from dwds.de on 2026-03-31.
If DWDS changes their HTML structure, re-capture and update these files.
"""

from pathlib import Path

import pytest

from maestro.vocab.dwds_parser import parse_html

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "dwds"


def _load(word: str) -> str:
    return (_FIXTURE_DIR / f"{word}.html").read_text()


@pytest.mark.integration
class TestDwdsRealHtml:
    def test_etwas_has_pos_and_senses(self):
        """'etwas' (Indefinitpronomen) should parse POS and senses."""
        entries = parse_html(_load("etwas"), "etwas")
        assert len(entries) >= 1
        assert entries[0].pos_abbrev == "Pron."
        assert len(entries[0].senses) >= 1

    def test_bitte_has_pos(self):
        """'bitte' (Partikel) should parse POS."""
        entries = parse_html(_load("bitte"), "bitte")
        assert len(entries) >= 1
        assert entries[0].pos_abbrev == "Part."

    def test_ich_has_pos(self):
        """'ich' (Personalpronomen) should parse POS."""
        entries = parse_html(_load("ich"), "ich")
        assert len(entries) >= 1
        assert entries[0].pos_abbrev == "Pron."

    def test_ja_has_senses(self):
        """'ja' has a DWDS data issue (POS = 'Fehler') but senses should still be extracted."""
        entries = parse_html(_load("ja"), "ja")
        assert len(entries) >= 1
        assert len(entries[0].senses) >= 1

    def test_gut_unchanged(self):
        """'gut' (Adjektiv) should still work — regression check."""
        entries = parse_html(_load("gut"), "gut")
        assert len(entries) >= 1
        assert entries[0].pos_abbrev == "Adj."
        assert len(entries[0].senses) >= 1

    def test_trinken_unchanged(self):
        """'trinken' (Verb) should still work — regression check."""
        entries = parse_html(_load("trinken"), "trinken")
        assert len(entries) >= 1
        assert entries[0].pos_abbrev == "V."
        assert len(entries[0].senses) >= 1

    def test_danke_has_pos(self):
        """'danke' (Partikel) should parse POS."""
        entries = parse_html(_load("danke"), "danke")
        assert len(entries) >= 1
        assert entries[0].pos_abbrev == "Part."
