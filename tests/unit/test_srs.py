import pytest
from datetime import date, timedelta
from types import SimpleNamespace

from maestro.vocab.srs import review


def make_card(**kwargs):
    defaults = dict(ease_factor=2.5, interval=1, repetitions=0, next_review=date.today())
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.unit
def test_fail_resets_streak():
    card = make_card(repetitions=5, interval=21, ease_factor=2.5)
    result = review(card, 1)
    assert result.repetitions == 0
    assert result.interval == 1


@pytest.mark.unit
def test_rating_2_also_resets():
    card = make_card(repetitions=3, interval=10, ease_factor=2.5)
    result = review(card, 2)
    assert result.repetitions == 0
    assert result.interval == 1


@pytest.mark.unit
def test_first_correct_review():
    card = make_card(repetitions=0)
    result = review(card, 4)
    assert result.repetitions == 1
    assert result.interval == 1


@pytest.mark.unit
def test_second_correct_review():
    card = make_card(repetitions=1, interval=1)
    result = review(card, 4)
    assert result.repetitions == 2
    assert result.interval == 6


@pytest.mark.unit
def test_third_review_uses_ease_factor():
    card = make_card(repetitions=2, interval=6, ease_factor=2.5)
    result = review(card, 4)
    assert result.interval == round(6 * 2.5)


@pytest.mark.unit
def test_ease_factor_increases_on_easy():
    card = make_card(ease_factor=2.5)
    result = review(card, 5)
    assert result.ease_factor > 2.5


@pytest.mark.unit
def test_ease_factor_decreases_on_hard():
    card = make_card(ease_factor=2.5)
    result = review(card, 3)
    assert result.ease_factor < 2.5


@pytest.mark.unit
def test_ease_factor_floor():
    card = make_card(ease_factor=1.4)
    result = review(card, 1)
    assert result.ease_factor >= 1.3


@pytest.mark.unit
def test_ease_factor_floor_on_many_failures():
    card = make_card(ease_factor=1.3)
    result = review(card, 1)
    assert result.ease_factor >= 1.3


@pytest.mark.unit
def test_next_review_date():
    card = make_card(repetitions=0)
    result = review(card, 4)
    assert result.next_review == date.today() + timedelta(days=result.interval)


@pytest.mark.unit
def test_next_review_date_after_long_interval():
    card = make_card(repetitions=2, interval=6, ease_factor=2.5)
    result = review(card, 4)
    assert result.next_review == date.today() + timedelta(days=result.interval)


@pytest.mark.unit
def test_successive_correct_reviews_accumulate():
    card = make_card(repetitions=0)
    card = review(card, 4)  # rep=1, interval=1
    card = review(card, 4)  # rep=2, interval=6
    assert card.repetitions == 2
    assert card.interval == 6
    card = review(card, 4)  # rep=3, interval=6*ease
    assert card.repetitions == 3
    assert card.interval > 6
