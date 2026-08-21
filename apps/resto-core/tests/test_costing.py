from decimal import Decimal

from app.costing import (
    coefficient,
    cost_per_pour,
    cost_percent,
    expected_ending_ml,
    glasses_per_bottle,
    ml_to_bottles,
    recipe_cost,
    theoretical_ml,
    variance_ml,
)


def test_sauvignon_blanc_by_the_glass():
    assert glasses_per_bottle(750, 150) == Decimal("5.0000")
    glass_cost = cost_per_pour(15, 750, 150)
    assert glass_cost == Decimal("3.00")
    assert cost_percent(glass_cost, 11) == Decimal("27.27")
    assert coefficient(11, glass_cost) == Decimal("3.6667")


def test_theoretical_usage_is_eight_bottles():
    used_ml = theoretical_ml(glasses_sold=40, pour_ml=150)
    assert used_ml == Decimal("6000")
    assert ml_to_bottles(used_ml, 750) == Decimal("8.0000")


def test_inventory_variance_detects_overpour():
    beginning = Decimal("12") * Decimal("750")  # 12 bottles
    purchased = Decimal("6") * Decimal("750")
    used = theoretical_ml(40, 150)  # 8 bottles
    expected = expected_ending_ml(beginning, purchased, used)
    counted = Decimal("8") * Decimal("750")  # 2 bottles missing vs expected 10
    assert ml_to_bottles(expected, 750) == Decimal("10.0000")
    assert ml_to_bottles(variance_ml(expected, counted), 750) == Decimal("-2.0000")


def test_sangria_recipe_cost():
    wine_cost_per_ml = Decimal("15") / Decimal("750")
    brandy_cost_per_ml = Decimal("22") / Decimal("750")
    juice_cost_per_ml = Decimal("4") / Decimal("1000")
    cost = recipe_cost(
        [
            (120, wine_cost_per_ml),
            (15, brandy_cost_per_ml),
            (30, juice_cost_per_ml),
        ]
    )
    assert cost == Decimal("2.96")
    assert cost_percent(cost, 12) == Decimal("24.67")
