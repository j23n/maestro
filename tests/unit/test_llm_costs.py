"""Unit tests for LLM cost calculation utilities."""

import pytest

from maestro.llm import compute_cost_usd
from maestro.models import CallType


def test_compute_cost_known_sonnet():
    cost = compute_cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert cost == pytest.approx(18.00)


def test_compute_cost_known_haiku():
    cost = compute_cost_usd("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
    assert cost == pytest.approx(4.80)
    sonnet_cost = compute_cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert cost < sonnet_cost


def test_compute_cost_known_opus():
    cost = compute_cost_usd("claude-opus-4-6", 1_000_000, 1_000_000)
    assert cost == pytest.approx(90.00)


def test_compute_cost_zero_tokens():
    assert compute_cost_usd("claude-sonnet-4-6", 0, 0) == 0.0


def test_compute_cost_unknown_model_uses_fallback():
    # Should not raise; should return Sonnet rates
    cost_unknown = compute_cost_usd("some-future-model", 1_000_000, 1_000_000)
    cost_sonnet = compute_cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert cost_unknown == pytest.approx(cost_sonnet)


def test_call_type_values_are_strings():
    for member in CallType:
        assert isinstance(member.value, str)
        assert len(member.value) > 0


def test_call_type_values_are_unique():
    values = [member.value for member in CallType]
    assert len(values) == len(set(values))
