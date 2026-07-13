"""Integer-only money arithmetic. No float ever enters a financial path.

Units:
- credits: signed integers, 1 credit = $0.01 of customer value.
- micro-USD: signed integers, $1.00 = 1,000,000 micro-USD.
- conversion: 1 credit = 10,000 micro-USD (fixed, non-configurable).

Provider rates that are not whole micro-USD amounts (e.g. $0.15/Mtok =
0.15 micro-USD per token) are carried as exact rationals (numerator,
denominator) and resolved with a single ceil at the end of a logical call.
"""

from __future__ import annotations

MICRO_USD_PER_CREDIT = 10_000
MICRO_USD_PER_USD = 1_000_000
CREDITS_PER_USD = 100


class MoneyTypeError(TypeError):
    """A non-integer reached financial arithmetic."""


def _check_int(*values) -> None:
    for v in values:
        # bool is an int subclass; reject it too — it is never money.
        if not isinstance(v, int) or isinstance(v, bool):
            raise MoneyTypeError(f"financial value must be int, got {type(v).__name__}: {v!r}")


def ceil_div(numerator: int, denominator: int) -> int:
    """Exact integer ceiling division for nonnegative numerators."""
    _check_int(numerator, denominator)
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator < 0:
        raise ValueError("ceil_div is defined for nonnegative numerators only")
    return -(-numerator // denominator)


def credits_to_micro_usd(credits: int) -> int:
    _check_int(credits)
    return credits * MICRO_USD_PER_CREDIT


def micro_usd_to_credits_ceil(micro_usd: int) -> int:
    """Final conversion of a logical call's micro-USD total into integer
    credits. This is the single place a ceil may round in Luna's favor."""
    return ceil_div(micro_usd, MICRO_USD_PER_CREDIT)


def usd_cents_to_micro_usd(cents: int) -> int:
    _check_int(cents)
    return cents * 10_000


def rational_cost_micro_usd(quantity: int, rate_numerator: int, rate_denominator: int) -> tuple[int, int]:
    """Cost of `quantity` native units at an exact rational micro-USD rate.

    Returns the cost itself as a rational (numerator, denominator) so callers
    can sum multiple dimensions exactly and apply one final ceil.
    """
    _check_int(quantity, rate_numerator, rate_denominator)
    if quantity < 0:
        raise ValueError("quantity must be nonnegative")
    if rate_numerator < 0 or rate_denominator <= 0:
        raise ValueError("rate must be nonnegative with positive denominator")
    return quantity * rate_numerator, rate_denominator


def sum_rationals(parts: list[tuple[int, int]]) -> tuple[int, int]:
    """Exact sum of rational (numerator, denominator) pairs."""
    total_num, total_den = 0, 1
    for num, den in parts:
        _check_int(num, den)
        if den <= 0:
            raise ValueError("denominator must be positive")
        total_num = total_num * den + num * total_den
        total_den *= den
    return total_num, total_den


def rational_ceil(numerator: int, denominator: int) -> int:
    """Ceil a nonnegative rational to an integer."""
    return ceil_div(numerator, denominator)


def rate_logical_call_credits(vendor_cost_micro_parts: list[tuple[int, int]], margin_micro_usd: int) -> tuple[int, int]:
    """Rate one logical call: exact vendor cost (rational micro-USD parts,
    e.g. one per fallback attempt/dimension) + one fixed context margin,
    then a single ceil to micro-USD and a single ceil to credits.

    Returns (vendor_cost_micro_usd_ceiled, final_credits).
    """
    _check_int(margin_micro_usd)
    if margin_micro_usd < 0:
        raise ValueError("margin must be nonnegative")
    num, den = sum_rationals(vendor_cost_micro_parts)
    vendor_micro = rational_ceil(num, den)
    # One logical call → one margin application → one final credit ceil.
    total_num = num + margin_micro_usd * den
    credits = ceil_div(total_num, den * MICRO_USD_PER_CREDIT)
    return vendor_micro, credits
