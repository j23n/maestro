import pytest
from types import SimpleNamespace

from maestro.routes.lezione import _activity_url
from maestro.routes.profilo import _build_grammar_by_level, _build_cf_by_level


def make_profile(**kwargs):
    defaults = dict(
        grammar_correct_counts={},
        grammar_error_counts={},
        grammar_recent_outcomes={},
        functions_counts={},
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def make_gp(code, level="A1", label=""):
    return SimpleNamespace(code=code, cefr_level=level, label=label or code)


def make_cf(code, level="A1", label=""):
    return SimpleNamespace(code=code, cefr_level=level, label=label or code)


@pytest.mark.unit
def test_activity_url():
    lesson_id = "abc123"
    assert _activity_url(lesson_id, 3) == "/lezione/abc123/activity/3"


@pytest.mark.unit
def test_activity_url_zero_index():
    assert _activity_url("xyz", 0) == "/lezione/xyz/activity/0"


@pytest.mark.unit
def test_build_grammar_by_level_grouping():
    points = [make_gp("GP_001", "A1"), make_gp("GP_002", "B1")]
    profile = make_profile()
    result = _build_grammar_by_level(points, profile)
    assert len(result["A1"]) == 1
    assert result["A1"][0]["point"].code == "GP_001"
    assert len(result["B1"]) == 1
    assert result["B1"][0]["point"].code == "GP_002"
    assert result["A2"] == []


@pytest.mark.unit
def test_build_grammar_mastered_flag_at_threshold():
    gp = make_gp("GP_001", "A1")
    # 5 outcomes, all True → 100% >= 80% → mastered
    profile = make_profile(grammar_recent_outcomes={"GP_001": [True] * 5})
    result = _build_grammar_by_level([gp], profile)
    assert result["A1"][0]["mastered"] is True


@pytest.mark.unit
def test_build_grammar_not_mastered_below_threshold():
    gp = make_gp("GP_001", "A1")
    # 5 outcomes, 3 True → 60% < 80% → not mastered
    profile = make_profile(grammar_recent_outcomes={"GP_001": [True, True, True, False, False]})
    result = _build_grammar_by_level([gp], profile)
    assert result["A1"][0]["mastered"] is False


@pytest.mark.unit
def test_build_grammar_not_mastered_too_few_reviews():
    gp = make_gp("GP_001", "A1")
    # Only 4 reviews (< 5 required) even if all correct
    profile = make_profile(grammar_recent_outcomes={"GP_001": [True, True, True, True]})
    result = _build_grammar_by_level([gp], profile)
    assert result["A1"][0]["mastered"] is False


@pytest.mark.unit
def test_build_grammar_no_profile():
    gp = make_gp("GP_001", "A1")
    result = _build_grammar_by_level([gp], None)
    skill = result["A1"][0]
    assert skill["correct"] == 0
    assert skill["errors"] == 0
    assert skill["mastered"] is False


@pytest.mark.unit
def test_build_cf_by_level_grouping():
    cfs = [make_cf("CF_001", "A1"), make_cf("CF_002", "A2")]
    profile = make_profile()
    result = _build_cf_by_level(cfs, profile)
    assert len(result["A1"]) == 1
    assert result["A1"][0]["cf"].code == "CF_001"
    assert len(result["A2"]) == 1


@pytest.mark.unit
def test_build_cf_demonstrated_at_count_3():
    cf = make_cf("CF_001", "A1")
    profile = make_profile(functions_counts={"CF_001": 3})
    result = _build_cf_by_level([cf], profile)
    assert result["A1"][0]["demonstrated"] is True


@pytest.mark.unit
def test_build_cf_not_demonstrated_below_3():
    cf = make_cf("CF_001", "A1")
    profile = make_profile(functions_counts={"CF_001": 2})
    result = _build_cf_by_level([cf], profile)
    assert result["A1"][0]["demonstrated"] is False


@pytest.mark.unit
def test_build_cf_no_profile():
    cf = make_cf("CF_001", "A1")
    result = _build_cf_by_level([cf], None)
    assert result["A1"][0]["count"] == 0
    assert result["A1"][0]["demonstrated"] is False
