import pytest
from hypothesis import given
from hypothesis import strategies as st

from concilia.matching.domain.amounts import (
    detraction_cents,
    detraction_rate,
    tolerance_cents,
    within_tolerance,
)
from concilia.matching.domain.explanations import format_pen, format_rate, join_documents
from concilia.matching.domain.model import EnginePolicy

POLICY = EnginePolicy()
balances = st.integers(min_value=1, max_value=10**12)


@pytest.mark.parametrize(
    ("balance", "expected"),
    [(10_000, 100), (20_000, 100), (20_199, 100), (20_200, 101), (1_000_000, 5_000)],
)
def test_tolerance_is_the_larger_of_the_minimum_and_the_rate_rounded_down(
    balance: int, expected: int
) -> None:
    assert tolerance_cents(balance, POLICY) == expected


@given(balances, st.integers(min_value=-(10**12), max_value=10**12))
def test_tolerance_ignores_the_sign_of_the_difference(balance: int, difference: int) -> None:
    assert within_tolerance(difference, balance, POLICY) == within_tolerance(
        -difference, balance, POLICY
    )
    assert tolerance_cents(balance, POLICY) >= POLICY.tolerance_min_cents


@pytest.mark.parametrize(
    ("balance", "rate", "expected"),
    [
        (117_000, 1200, 14_000),
        (250_000, 1000, 25_000),
        (500, 1000, 100),
        (499, 1000, 0),
        (1_250, 1200, 200),
        (12_345, 1000, 1_200),
    ],
)
def test_detraction_is_rounded_half_up_to_whole_soles(
    balance: int, rate: int, expected: int
) -> None:
    assert detraction_cents(balance, rate) == expected


@given(balances, st.integers(min_value=1, max_value=10_000))
def test_detraction_is_the_nearest_whole_sol(balance: int, rate: int) -> None:
    detraction = detraction_cents(balance, rate)

    assert detraction % 100 == 0
    assert abs(detraction * 10_000 - balance * rate) <= 50 * 10_000


@pytest.mark.parametrize(
    ("amount", "balance", "expected"),
    [
        (103_000, 117_000, 1200),
        (225_000, 250_000, 1000),
        (225_100, 250_000, 1000),
        (225_101, 250_000, None),
        (117_000, 117_000, None),
    ],
)
def test_detraction_rate(amount: int, balance: int, expected: int | None) -> None:
    assert detraction_rate(amount, balance, POLICY) == expected


def test_detraction_rate_prefers_the_closest_rate_and_then_the_lowest() -> None:
    policy = EnginePolicy(detraction_rates_bp=(1200, 1000))

    assert detraction_rate(8_950, 10_000, policy) == 1000
    assert detraction_rate(8_900, 10_000, policy) == 1000
    assert detraction_rate(8_850, 10_000, policy) == 1200


@pytest.mark.parametrize(
    ("cents", "expected"),
    [(0, "S/ 0.00"), (5, "S/ 0.05"), (-50, "S/ -0.50"), (123_456_789, "S/ 1,234,567.89")],
)
def test_format_pen(cents: int, expected: str) -> None:
    assert format_pen(cents) == expected


@pytest.mark.parametrize(
    ("rate", "expected"), [(1000, "10 %"), (1250, "12.5 %"), (1205, "12.05 %"), (50, "0.5 %")]
)
def test_format_rate(rate: int, expected: str) -> None:
    assert format_rate(rate) == expected


def test_join_documents() -> None:
    assert join_documents(["F001-1"]) == "F001-1"
    assert join_documents(["F001-1", "F001-2"]) == "F001-1 y F001-2"
    assert join_documents(["F001-1", "F001-2", "F001-3"]) == "F001-1, F001-2 y F001-3"
