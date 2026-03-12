"""Unit tests for maestro.vocab.pos — POS tag mapping."""

import pytest

from maestro.vocab.pos import matches_pos


class TestMatchesPos:
    """matches_pos(epub_pos, spacy_pos) maps EPUB abbreviations to spaCy universal POS."""

    @pytest.mark.parametrize(
        "epub_pos,spacy_pos",
        [
            ("s.m.", "NOUN"),
            ("s.f.", "NOUN"),
            ("s.m./f.", "NOUN"),
            ("v.tr.", "VERB"),
            ("v.intr.", "VERB"),
            ("v.rifl.", "VERB"),
            ("v.", "VERB"),
            ("agg.", "ADJ"),
            ("avv.", "ADV"),
            ("prep.", "ADP"),
            ("pron.", "PRON"),
            ("art.", "DET"),
            ("cong.", "CCONJ"),
            ("cong.", "SCONJ"),
            ("inter.", "INTJ"),
            ("num.", "NUM"),
        ],
    )
    def test_matching_pairs(self, epub_pos, spacy_pos):
        assert matches_pos(epub_pos, spacy_pos) is True

    @pytest.mark.parametrize(
        "epub_pos,spacy_pos",
        [
            ("s.m.", "VERB"),
            ("v.tr.", "NOUN"),
            ("agg.", "NOUN"),
            ("avv.", "VERB"),
        ],
    )
    def test_non_matching_pairs(self, epub_pos, spacy_pos):
        assert matches_pos(epub_pos, spacy_pos) is False

    @pytest.mark.parametrize("spacy_pos", ["X", "PUNCT", "SYM", "SPACE", ""])
    def test_unknown_spacy_pos_returns_false(self, spacy_pos):
        assert matches_pos("s.m.", spacy_pos) is False

    def test_empty_epub_pos(self):
        assert matches_pos("", "NOUN") is False

    def test_both_empty(self):
        assert matches_pos("", "") is False
