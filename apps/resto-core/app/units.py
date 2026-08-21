from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

from app.costing import money

ZERO = Decimal("0")
THREE = Decimal("0.001")
_COUNT_PACK = re.compile(
    r"(?P<count>\d+)\s*/\s*(?P<each>\d+(?:\.\d+)?)\s*(?P<unit>lbs?|pounds?|oz|ounces?|kg|g|grams?|gal|gallons?|qt|quarts?|ml|l|each|ea|ct|pc|dz|doz|dozen)\b",
    re.I,
)
GRAM = Decimal("1")
ML = Decimal("1")

TO_GRAMS = {
    "g": GRAM,
    "gram": GRAM,
    "grams": GRAM,
    "kg": Decimal("1000"),
    "oz": Decimal("28.3495"),
    "ounce": Decimal("28.3495"),
    "lb": Decimal("453.592"),
    "lbs": Decimal("453.592"),
    "pound": Decimal("453.592"),
    "pounds": Decimal("453.592"),
}

TO_ML = {
    "ml": ML,
    "l": Decimal("1000"),
    "liter": Decimal("1000"),
    "litre": Decimal("1000"),
    "qt": Decimal("946.353"),
    "quart": Decimal("946.353"),
    "gal": Decimal("3785.41"),
    "gallon": Decimal("3785.41"),
    "cup": Decimal("236.588"),
    "floz": Decimal("29.5735"),
}

TO_EACH = {
    "each": Decimal("1"),
    "ea": Decimal("1"),
    "ct": Decimal("1"),
    "pc": Decimal("1"),
    "piece": Decimal("1"),
    "unit": Decimal("1"),
    "dz": Decimal("12"),
    "doz": Decimal("12"),
    "dozen": Decimal("12"),
}

_EACH_CT = re.compile(
    r"(?P<each>\d+(?:\.\d+)?)\s*(?P<unit>lbs?|pounds?|oz|ounces?|kg|g|grams?|gal|gallons?|qt|quarts?|ml|l)\b\.?,?\s*(?P<count>\d+)\s*(?:ct|count|pk|pack)\b",
    re.I,
)
_CASE_PACK = re.compile(
    r"(?P<each>\d+(?:\.\d+)?)\s*(?P<unit>lbs?|pounds?|oz|ounces?|kg|g|grams?|gal|gallons?|qt|quarts?|ml|l)\b\.?\s*[-–]\s*(?P<count>\d+)\s*/\s*(?:case|cs)\b",
    re.I,
)
_PACK = re.compile(
    r"(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>lbs?|pounds?|oz|ounces?|kg|g|grams?|gal|gallons?|qt|quarts?|ml|l|each|ea|ct|pc|dz|doz|dozen)\b",
    re.I,
)
_TRAIL_CASE = re.compile(r"[-–]\s*(?P<count>\d+)\s*/\s*(?:case|cs)\b", re.I)
_QTY_SUFFIX = re.compile(r"\bQty\s+(\d+(?:\.\d+)?)\s*$", re.I)


def norm_unit(unit: str) -> str:
    text = str(unit or "").strip().lower().rstrip(".")
    aliases = {
        "pound": "lb",
        "pounds": "lb",
        "lbs": "lb",
        "ounces": "oz",
        "ounce": "oz",
        "grams": "g",
        "gram": "g",
        "kilogram": "kg",
        "kilograms": "kg",
        "liters": "l",
        "litres": "l",
        "gallon": "gal",
        "gallons": "gal",
        "quart": "qt",
        "quarts": "qt",
        "pieces": "each",
        "piece": "each",
        "ea": "each",
        "ct": "each",
        "pc": "each",
        "dozen": "dozen",
        "doz": "dozen",
        "dz": "dozen",
    }
    return aliases.get(text, text)


def family(unit: str) -> str | None:
    key = norm_unit(unit)
    if key in TO_GRAMS or key == "lb" or key == "oz":
        return "weight"
    if key in TO_ML:
        return "volume"
    if key in TO_EACH or key == "each" or key == "dozen":
        return "count"
    return None


def to_base(qty: Decimal | int | float | str, unit: str, base_unit: str) -> Decimal | None:
    amount = Decimal(str(qty or 0))
    src = family(unit)
    dest = family(base_unit)
    if src is None or dest is None or src != dest:
        return None
    if src == "weight":
        grams = amount * TO_GRAMS[norm_unit(unit)]
        return grams / TO_GRAMS[norm_unit(base_unit)]
    if src == "volume":
        milliliters = amount * TO_ML[norm_unit(unit)]
        return milliliters / TO_ML[norm_unit(base_unit)]
    each = amount * TO_EACH.get(norm_unit(unit), Decimal("1"))
    return each / TO_EACH.get(norm_unit(base_unit), Decimal("1"))


def parse_pack(description: str, fallback_qty: Decimal | int | float = 0, fallback_unit: str = "") -> tuple[Decimal, str]:
    text = str(description or "")
    qty = ZERO
    unit = ""
    used_case = False
    counted = _COUNT_PACK.search(text)
    if counted:
        qty = Decimal(counted.group("count")) * Decimal(counted.group("each"))
        unit = counted.group("unit")
        used_case = True
    else:
        counted = _CASE_PACK.search(text)
        if counted:
            qty = Decimal(counted.group("each")) * Decimal(counted.group("count"))
            unit = counted.group("unit")
            used_case = True
        else:
            counted = _EACH_CT.search(text)
            if counted:
                qty = Decimal(counted.group("each")) * Decimal(counted.group("count"))
                unit = counted.group("unit")
            else:
                matches = list(_PACK.finditer(text))
                if matches:
                    chosen = matches[-1]
                    qty = Decimal(chosen.group("qty"))
                    unit = chosen.group("unit")
                elif fallback_qty and fallback_unit:
                    qty = Decimal(str(fallback_qty))
                    unit = fallback_unit
    if not used_case and qty > 0:
        trail = _TRAIL_CASE.search(text)
        if trail:
            qty *= Decimal(trail.group("count"))
    suffix = _QTY_SUFFIX.search(text)
    if suffix and qty > 0:
        qty *= Decimal(suffix.group(1))
    return qty, norm_unit(unit or fallback_unit)


def unit_money(value) -> Decimal:
    amount = Decimal(str(value))
    if amount >= 1:
        return money(amount)
    return amount.quantize(THREE, rounding=ROUND_HALF_UP)


def comparable_cost(pack_price, pack_qty, pack_unit: str, compare_unit: str) -> Decimal | None:
    converted = to_base(pack_qty, pack_unit, compare_unit)
    if converted is None or converted <= 0:
        return None
    return unit_money(Decimal(str(pack_price)) / converted)
