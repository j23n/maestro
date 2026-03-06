import pytest

from maestro.lezione.slots import _allocate_slots


@pytest.mark.unit
def test_short_session():
    slots = _allocate_slots(10)
    assert slots["grammar"] == 1
    assert slots["drill"] == 3


@pytest.mark.unit
def test_below_threshold_same_as_short():
    slots_5 = _allocate_slots(5)
    slots_10 = _allocate_slots(10)
    assert slots_5 == slots_10


@pytest.mark.unit
def test_medium_session():
    slots = _allocate_slots(20)
    assert slots["grammar"] == 2
    assert slots["drill"] == 6


@pytest.mark.unit
def test_medium_session_15():
    slots = _allocate_slots(15)
    assert slots["grammar"] == 2
    assert slots["drill"] == 6


@pytest.mark.unit
def test_long_session():
    slots = _allocate_slots(40)
    assert slots["grammar"] == 3
    assert slots["drill"] == 12


@pytest.mark.unit
def test_above_20_is_long():
    slots_25 = _allocate_slots(25)
    slots_40 = _allocate_slots(40)
    assert slots_25 == slots_40


@pytest.mark.unit
def test_all_activity_types_present():
    for duration in [5, 15, 30]:
        slots = _allocate_slots(duration)
        for key in ("grammar", "drill", "vocab_review", "reading", "writing", "speaking"):
            assert key in slots, f"Missing key '{key}' for duration={duration}"


@pytest.mark.unit
def test_vocab_review_increases_with_duration():
    short = _allocate_slots(5)
    medium = _allocate_slots(15)
    long_ = _allocate_slots(40)
    assert short["vocab_review"] < medium["vocab_review"] < long_["vocab_review"]
