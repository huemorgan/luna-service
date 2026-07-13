"""039/001 — integer money arithmetic. No float ever survives these paths."""

from __future__ import annotations

import pytest

from cloud.billing.money import (
    MICRO_USD_PER_CREDIT,
    MoneyTypeError,
    ceil_div,
    credits_to_micro_usd,
    micro_usd_to_credits_ceil,
    rate_logical_call_credits,
    rational_ceil,
    rational_cost_micro_usd,
    sum_rationals,
    usd_cents_to_micro_usd,
)


def test_unit_identity():
    # 1 credit = $0.01 = 10,000 micro-USD; $1 = 100 credits.
    assert MICRO_USD_PER_CREDIT == 10_000
    assert credits_to_micro_usd(1) == 10_000
    assert usd_cents_to_micro_usd(100) == 1_000_000
    assert micro_usd_to_credits_ceil(1_000_000) == 100


def test_ceil_div():
    assert ceil_div(0, 10) == 0
    assert ceil_div(10, 10) == 1
    assert ceil_div(11, 10) == 2
    assert ceil_div(1, 10_000) == 1
    with pytest.raises(ValueError):
        ceil_div(-1, 10)
    with pytest.raises(ValueError):
        ceil_div(1, 0)


def test_floats_and_bools_rejected():
    with pytest.raises(MoneyTypeError):
        credits_to_micro_usd(1.0)  # type: ignore[arg-type]
    with pytest.raises(MoneyTypeError):
        ceil_div(True, 10)  # type: ignore[arg-type]
    with pytest.raises(MoneyTypeError):
        rational_cost_micro_usd(10, 1.5, 1)  # type: ignore[arg-type]


def test_rate_identity_dollars_per_mtok():
    # $N per 1M tokens == N micro-USD per token. Claude Opus input: $5/Mtok.
    num, den = rational_cost_micro_usd(1_000_000, 5, 1)
    assert num // den == 5_000_000  # $5 for a million tokens
    # gpt-4o-mini input $0.15/Mtok = 3/20 micro-USD per token.
    num, den = rational_cost_micro_usd(1_000_000, 3, 20)
    assert num // den == 150_000  # $0.15


def test_sum_rationals_exact():
    # 1/3 + 1/6 = 1/2 exactly — no float drift.
    num, den = sum_rationals([(1, 3), (1, 6)])
    assert num * 2 == den
    assert rational_ceil(num, den) == 1


def test_single_ceil_per_logical_call():
    # Two dimensions that each round up alone but not together must ceil once.
    # 3 tokens at 3/20 each = 9/20; twice = 18/20 → 1 micro-USD total,
    # not ceil(9/20)+ceil(9/20) = 2.
    parts = [rational_cost_micro_usd(3, 3, 20), rational_cost_micro_usd(3, 3, 20)]
    vendor_micro, credits = rate_logical_call_credits(parts, margin_micro_usd=0)
    assert vendor_micro == 1
    assert credits == 1  # sub-credit total still bills a minimum whole credit


def test_rate_logical_call_with_margin():
    # 10k in / 2k out on Opus ($5/$25 per Mtok) + agent-top margin 20,000.
    parts = [
        rational_cost_micro_usd(10_000, 5, 1),
        rational_cost_micro_usd(2_000, 25, 1),
    ]
    vendor_micro, credits = rate_logical_call_credits(parts, margin_micro_usd=20_000)
    assert vendor_micro == 100_000  # $0.10 vendor
    # (100,000 + 20,000) / 10,000 = 12 credits exactly.
    assert credits == 12


def test_margin_applied_once_not_per_part():
    parts = [(1, 1), (1, 1)]  # 2 micro-USD vendor
    _, credits = rate_logical_call_credits(parts, margin_micro_usd=9_999)
    # 2 + 9,999 = 10,001 → 2 credits. Per-part margin would give 2 credits
    # from margin alone per part (wrong).
    assert credits == 2
    with pytest.raises(ValueError):
        rate_logical_call_credits(parts, margin_micro_usd=-1)
