"""Unit tests for scenario chaining: match_scenario_to_context and pick_scenario
with last_scenario_slug bias. No DB required — scenario objects are mocked."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from maestro.lessons.selection import match_scenario_to_context


def _scenario(
    slug: str,
    label: str,
    description: str = "",
    depths: list[str] | None = None,
    gp_codes: list[str] | None = None,
    cf_codes: list[str] | None = None,
    phase: int = 1,
):
    return SimpleNamespace(
        slug=slug,
        label=label,
        description=description,
        depths=depths or [],
        gp_codes=gp_codes or [],
        cf_codes=cf_codes or [],
        phase=phase,
    )


@pytest.fixture
def bar_scenario():
    return _scenario(
        "al-bar",
        "Ordering coffee",
        "Ordering coffee at an Italian bar",
        ["order a coffee", "chat with barista", "pay the bill"],
    )


@pytest.fixture
def station_scenario():
    return _scenario(
        "in-stazione",
        "At the train station",
        "Buying a train ticket",
        ["ask timetable", "buy ticket", "find the platform"],
    )


@pytest.fixture
def date_scenario():
    return _scenario(
        "first-date",
        "First date small talk",
        "Small talk on a first date",
        ["meet up", "shared interests", "see you again"],
    )


@pytest.mark.unit
def test_match_empty_context_returns_none(bar_scenario):
    assert match_scenario_to_context("", [bar_scenario]) is None
    assert match_scenario_to_context("   ", [bar_scenario]) is None


@pytest.mark.unit
def test_match_no_scenarios_returns_none():
    assert match_scenario_to_context("anything at all", []) is None


@pytest.mark.unit
def test_match_picks_best_keyword_overlap(
    bar_scenario, station_scenario, date_scenario
):
    picked = match_scenario_to_context(
        "I want to order coffee at a bar tomorrow",
        [bar_scenario, station_scenario, date_scenario],
    )
    assert picked is not None and picked.slug == "al-bar"


@pytest.mark.unit
def test_match_label_match_weighted_double(bar_scenario, station_scenario):
    # "station" only appears in the station label; "ordering" would match bar's
    # label. "train station" should pick station over bar even though bar has a
    # longer description.
    picked = match_scenario_to_context(
        "train station timetable please",
        [bar_scenario, station_scenario],
    )
    assert picked is not None and picked.slug == "in-stazione"


@pytest.mark.unit
def test_match_returns_none_below_threshold(bar_scenario, station_scenario):
    # "Ferragosto" doesn't match anything meaningful.
    picked = match_scenario_to_context(
        "Tell me about ferragosto",
        [bar_scenario, station_scenario],
    )
    assert picked is None


@pytest.mark.unit
def test_match_respects_stoplist(bar_scenario):
    # Words like "the", "a", "at", "to" shouldn't trigger matches alone.
    picked = match_scenario_to_context("the a at to", [bar_scenario])
    assert picked is None


@pytest.mark.unit
def test_match_short_tokens_dropped(bar_scenario):
    # Two-letter tokens are dropped before scoring.
    picked = match_scenario_to_context("on it at", [bar_scenario])
    assert picked is None


# --- pick_scenario last_scenario_slug tests ---


async def _run_pick(
    *, scenarios, last_scenario_slug=None, profile=None, cefr_level="A1"
):
    from maestro.lessons.selection import pick_scenario

    # Stabilise jitter so tests assert on deterministic ordering.
    random.seed(0)
    return await pick_scenario(
        profile,
        cefr_level,
        scenarios=scenarios,
        language="it",
        last_scenario_slug=last_scenario_slug,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pick_scenario_penalises_last_slug(
    monkeypatch, bar_scenario, station_scenario
):
    # Make get_available_scenarios and get_max_available_depth deterministic.
    from maestro.lessons import selection

    monkeypatch.setattr(selection, "get_available_scenarios", lambda p, s: s)
    monkeypatch.setattr(selection, "get_max_available_depth", lambda *a, **k: 3)

    picked, _ = await _run_pick(
        scenarios=[bar_scenario, station_scenario],
        last_scenario_slug="al-bar",
    )
    assert picked.slug == "in-stazione"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pick_scenario_rewards_overlap_with_last(monkeypatch):
    from maestro.lessons import selection

    monkeypatch.setattr(selection, "get_available_scenarios", lambda p, s: s)
    monkeypatch.setattr(selection, "get_max_available_depth", lambda *a, **k: 3)

    last = _scenario(
        "past-lesson",
        "Past",
        "Past",
        depths=["d"],
        gp_codes=["GP1", "GP2"],
        cf_codes=["CF1"],
    )
    shared = _scenario(
        "shared",
        "Shared",
        "Shared",
        depths=["d"],
        gp_codes=["GP1", "GP2"],
        cf_codes=["CF1"],
    )
    unrelated = _scenario(
        "unrelated",
        "Unrelated",
        "Unrelated",
        depths=["d"],
        gp_codes=["GPX"],
        cf_codes=["CFX"],
    )

    random.seed(42)
    picked, _ = await _run_pick(
        scenarios=[last, shared, unrelated],
        last_scenario_slug="past-lesson",
    )
    # "past-lesson" is penalised; "shared" has +1.5 overlap bonus over "unrelated".
    assert picked.slug == "shared"
