"""Integration tests for the German A0 discover pipeline.

End-to-end: surface form → lemma resolution → headword match →
DWDS enrichment (POS + senses) → LLM definition generation.

Fixtures:
  - tests/fixtures/de_a0_headwords.json — strict subset of dwds_headwords.json
  - tests/fixtures/dwds/*.html — cached DWDS HTML pages
  - tests/fixtures/de_vocab_definitions.json — cached LLM responses
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from maestro.models import VocabularyWord, VocabularyWordDefinition
from maestro.vocab import cache as _vocab_cache

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
_DWDS_HTML_DIR = _FIXTURES_DIR / "dwds"

# Superscript stripping regex — same as dwds_ingest.py
_SUPERSCRIPT_RE = re.compile(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_headwords() -> list[str]:
    """Load and deduplicate headwords from the A0 fixture — mirrors dwds_ingest logic."""
    raw: dict[str, str] = json.loads(
        (_FIXTURES_DIR / "de_a0_headwords.json").read_text()
    )
    seen: set[str] = set()
    words: list[str] = []
    for headword in raw:
        stripped = _SUPERSCRIPT_RE.sub("", headword).strip()
        normalised = unicodedata.normalize("NFC", stripped)
        if normalised and normalised not in seen:
            seen.add(normalised)
            words.append(normalised)
    return words


def _make_mock_call_api():
    """Create a mock for _call_api that returns cached LLM responses."""
    cached = json.loads((_FIXTURES_DIR / "de_vocab_definitions.json").read_text())

    async def _mock_call_api(batch, max_tokens=16384, *, language):
        from maestro.vocab.generate_definitions import _word_key

        result = {}
        for word in batch:
            key = _word_key(word)
            if key in cached:
                result[key] = cached[key]
            else:
                # Case-insensitive fallback
                for k in cached:
                    if k.lower() == key.lower():
                        result[key] = cached[k]
                        break
        return result

    return _mock_call_api


def _mock_fetch_and_parse():
    """Create a mock for fetch_and_parse that reads from cached DWDS HTML."""
    from maestro.vocab.dwds_parser import parse_html

    async def _fetch(word, *, client=None):
        for variant in [word, word.lower(), word.capitalize()]:
            html_path = _DWDS_HTML_DIR / f"{variant}.html"
            if html_path.exists():
                return parse_html(html_path.read_text(), word)
        return []

    return _fetch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def de_a0_words(db) -> dict[str, list[VocabularyWord]]:
    """Insert bare German VocabularyWord docs and seed the vocab cache.

    Returns the word_index dict (lowered headword → [VocabularyWord]).
    """
    from maestro.utils import utcnow

    words = _load_headwords()
    now = utcnow()
    idx: dict[str, list[VocabularyWord]] = {}

    for word in words:
        doc = VocabularyWord(
            word=word,
            part_of_speech="",
            language="de",
            senses=[],
            cefr_level=None,
            created_at=now,
            updated_at=now,
        )
        await doc.insert()
        idx.setdefault(word.lower(), []).append(doc)

    _vocab_cache.seed(words=idx, defs={}, language="de")
    return idx


@pytest.fixture(autouse=True)
def _reset_discover_state():
    """Reset discover's deduplication set between tests."""
    from maestro.vocab import discover

    discover._pending_def_gen.clear()
    yield
    discover._pending_def_gen.clear()
    _vocab_cache.invalidate("de")


async def _run_pipeline(de_a0_words, text: str) -> str:
    """Run discover() + drain background tasks, return annotated HTML."""
    from maestro.utils import drain_background_tasks
    from maestro.vocab.discover import discover

    html = f'<span lang="de">{text}</span>'

    with (
        patch(
            "maestro.vocab.dwds_parser.fetch_and_parse",
            side_effect=_mock_fetch_and_parse(),
        ),
        patch(
            "maestro.vocab.generate_definitions._call_api",
            side_effect=_make_mock_call_api(),
        ),
        patch(
            "maestro.vocab.discover.get_cefr_level",
            new_callable=AsyncMock,
            return_value="A0",
        ),
        patch("maestro.vocab.discover._generate_missing_audio", new_callable=AsyncMock),
    ):
        result = await discover(
            html, student_id=None, create_cards=False, language="de"
        )
        await drain_background_tasks()

    return result


# ---------------------------------------------------------------------------
# End-to-end pipeline: surface → headword → POS (DWDS) → definitions (LLM)
# ---------------------------------------------------------------------------

# Each test case: (dialogue text, [(surface, lemma_key, headword, expected_pos)])
#
# "lemma_key" = lowercase key in the word_index
# "headword"  = the specific VocabularyWord.word that should have this POS after enrichment
# "expected_pos" = POS assigned by the DWDS parser from cached HTML
#
# After sibling enrichment, ALL entries under the same lemma_key get enriched.
# So even though the first match (bare, no POS) might pick the wrong case variant,
# the correct headword+POS combination exists in the DB after the pipeline runs.

_PIPELINE_CASES = [
    pytest.param(
        "Möchten Sie etwas trinken?",
        [
            ("Möchten", "mögen", "mögen", "V."),
            ("Sie", "sie", "Sie", "Pron."),
            ("etwas", "etwas", "etwas", "Pron."),
            ("trinken", "trinken", "trinken", "V."),
        ],
        id="would-you-like-to-drink",
    ),
    pytest.param(
        "Ja, ich möchte einen Kaffee, bitte.",
        [
            ("ich", "ich", "ich", "Pron."),
            ("möchte", "mögen", "mögen", "V."),
            ("Kaffee", "kaffee", "Kaffee", "Subst."),
            ("bitte", "bitte", "bitte", "Part."),
        ],
        id="yes-coffee-please",
    ),
    pytest.param(
        "Mit Milch? Nein, danke.",
        [
            ("Mit", "mit", "mit", "Praep."),
            ("Milch", "milch", "Milch", "Subst."),
            ("Nein", "nein", "nein", "Part."),
            ("danke", "danke", "danke", "Part."),
        ],
        id="with-milk-no-thanks",
    ),
    pytest.param(
        "Bitte schön! Danke schön!",
        [
            ("bitte", "bitte", "bitte", "Part."),
            ("schön", "schön", "schön", "Adj."),
            ("danke", "danke", "danke", "Part."),
        ],
        id="youre-welcome-thank-you",
    ),
    pytest.param(
        "Guten Abend. Entschuldigung, ich möchte ein Wasser, bitte.",
        [
            ("Guten", "gut", "gut", "Adj."),
            ("Abend", "abend", "Abend", "Subst."),
            ("Entschuldigung", "entschuldigung", "Entschuldigung", "Subst."),
            ("ich", "ich", "ich", "Pron."),
            ("möchte", "mögen", "mögen", "V."),
            ("Wasser", "wasser", "Wasser", "Subst."),
            ("bitte", "bitte", "bitte", "Part."),
        ],
        id="good-evening-excuse-me",
    ),
    pytest.param(
        "Ja, natürlich. Noch etwas?",
        [
            ("natürlich", "natürlich", "natürlich", "Adj."),
            ("Noch", "noch", "noch", "Adv."),
            ("etwas", "etwas", "etwas", "Pron."),
        ],
        id="of-course-anything-else",
    ),
    pytest.param(
        "Auf Wiedersehen!",
        [
            ("Auf", "auf", "auf", "Praep."),
            ("Wiedersehen", "wiedersehen", "Wiedersehen", "Subst."),
        ],
        id="goodbye",
    ),
]


@pytest.mark.integration
@pytest.mark.parametrize("text, expected_mappings", _PIPELINE_CASES)
async def test_de_a0_pipeline(de_a0_words, text, expected_mappings):
    """End-to-end German discover: surface → headword → POS → definitions.

    Runs the full pipeline (match → DWDS enrich → LLM definitions) on each
    A0.1 dialogue fragment. After enrichment + definition generation:

    1. The expected headword has the correct POS from the DWDS parser.
    2. A1–B2 VocabularyWordDefinition docs exist for each enriched word.
    3. The surface form appears annotated in the returned HTML.
    """
    result = await _run_pipeline(de_a0_words, text)

    # The HTML should contain vocab annotations
    assert "vocab-word" in result

    all_defs = await VocabularyWordDefinition.find_all().to_list()

    for surface, lemma_key, expected_headword, expected_pos in expected_mappings:
        # 1. After sibling enrichment, the correct headword+POS exists
        siblings = de_a0_words.get(lemma_key, [])
        match = next(
            (w for w in siblings if w.word == expected_headword and w.part_of_speech),
            None,
        )
        assert match is not None, (
            f"surface {surface!r}: no enriched VocabularyWord found for "
            f"headword={expected_headword!r} under key {lemma_key!r}\n"
            f"  siblings: {[(w.word, w.part_of_speech) for w in siblings]}"
        )
        assert match.part_of_speech == expected_pos, (
            f"surface {surface!r}: expected POS {expected_pos!r} for "
            f"{expected_headword!r}, got {match.part_of_speech!r}"
        )

        # 2. Definitions were generated (A1–B2)
        word_defs = [
            d
            for d in all_defs
            if (str(d.word.ref.id) if hasattr(d.word, "ref") else str(d.word.id))
            == str(match.id)
        ]
        levels = {d.student_level for d in word_defs}
        assert levels == {"A1", "A2", "B1", "B2"}, (
            f"surface {surface!r}: expected A1–B2 definitions for "
            f"{expected_headword!r} ({expected_pos}), got levels={levels}"
        )

        # 3. Each definition has content
        for d in word_defs:
            assert d.senses, (
                f"surface {surface!r}: empty senses for {expected_headword!r} "
                f"at {d.student_level}"
            )
            assert d.translation, (
                f"surface {surface!r}: empty translation for {expected_headword!r} "
                f"at {d.student_level}"
            )


# ---------------------------------------------------------------------------
# Sibling enrichment — both case variants get POS
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_de_sibling_enrichment(de_a0_words):
    """Both 'gut' (Adj.) and 'Gut' (Subst.) should be enriched under the same key."""
    await _run_pipeline(de_a0_words, "Das ist gut.")

    gut_entries = de_a0_words.get("gut", [])
    pos_by_word = {w.word: w.part_of_speech for w in gut_entries if w.part_of_speech}
    assert pos_by_word.get("gut") == "Adj.", f"got {pos_by_word}"
    assert pos_by_word.get("Gut") == "Subst.", f"got {pos_by_word}"
