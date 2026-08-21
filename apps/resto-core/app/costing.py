from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

TWOPLACES = Decimal("0.01")
FOURPLACES = Decimal("0.0001")
ZERO = Decimal("0")


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def ratio(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(FOURPLACES, rounding=ROUND_HALF_UP)


def glasses_per_bottle(bottle_ml: Decimal | int, pour_ml: Decimal | int) -> Decimal:
    bottle = Decimal(str(bottle_ml))
    pour = Decimal(str(pour_ml))
    if pour <= 0:
        raise ValueError("Pour size must be greater than 0")
    if bottle <= 0:
        raise ValueError("Bottle size must be greater than 0")
    return ratio(bottle / pour)


def cost_per_pour(bottle_cost: Decimal | int | float, bottle_ml: Decimal | int, pour_ml: Decimal | int) -> Decimal:
    bottle = Decimal(str(bottle_ml))
    pour = Decimal(str(pour_ml))
    if bottle <= 0:
        raise ValueError("Bottle size must be greater than 0")
    return money(Decimal(str(bottle_cost)) * (pour / bottle))


def cost_percent(cost: Decimal | int | float, selling_price: Decimal | int | float) -> Decimal:
    price = Decimal(str(selling_price))
    if price <= 0:
        return ZERO
    return money((Decimal(str(cost)) / price) * Decimal(100))


def coefficient(selling_price: Decimal | int | float, cost: Decimal | int | float) -> Decimal:
    cost_d = Decimal(str(cost))
    if cost_d <= 0:
        return ZERO
    return ratio(Decimal(str(selling_price)) / cost_d)


def theoretical_ml(glasses_sold: Decimal | int, pour_ml: Decimal | int, bottles_sold: Decimal | int = 0, bottle_ml: Decimal | int = 750) -> Decimal:
    return (Decimal(str(glasses_sold)) * Decimal(str(pour_ml))) + (
        Decimal(str(bottles_sold)) * Decimal(str(bottle_ml))
    )


def ml_to_bottles(volume_ml: Decimal | int | float, bottle_ml: Decimal | int = 750) -> Decimal:
    size = Decimal(str(bottle_ml))
    if size <= 0:
        raise ValueError("Bottle size must be greater than 0")
    return ratio(Decimal(str(volume_ml)) / size)


def expected_ending_ml(beginning_ml: Decimal, purchased_ml: Decimal, theoretical_used_ml: Decimal) -> Decimal:
    return Decimal(str(beginning_ml)) + Decimal(str(purchased_ml)) - Decimal(str(theoretical_used_ml))


def variance_ml(expected_ending_ml_value: Decimal, counted_ml: Decimal) -> Decimal:
    return Decimal(str(counted_ml)) - Decimal(str(expected_ending_ml_value))


def recipe_cost(lines: Iterable[tuple[Decimal | int | float, Decimal | int | float]]) -> Decimal:
    """lines are (quantity_in_base_unit, cost_per_base_unit)."""
    total = ZERO
    for qty, unit_cost in lines:
        total += Decimal(str(qty)) * Decimal(str(unit_cost))
    return money(total)
