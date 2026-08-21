"""Turn vendor OCR / POS strings into a name a cook would recognize."""

from __future__ import annotations

import re
from decimal import Decimal

from app.units import parse_pack

_MONEY_TAIL = re.compile(r"(?:\s+\$?\d{1,4}(?:,\d{3})*(?:\.\d{2}))+\s*$")
_LEADING_CODES = re.compile(r"^(?:#?\d{1,8}\s+){1,}")
_TRAILING_INT = re.compile(r"(?:\s+\d{1,4})+\s*$")
_QTY_TAIL = re.compile(r"\s+Qty\s+\d+(?:\.\d+)?\s*$", re.I)
_SKU_TOKEN = re.compile(r"\b(?:sku|upc|item#?)\s*[:#]?\s*[A-Z0-9-]+\b", re.I)
_INCH = re.compile(r'(\d+)\s*"')
_COUNT = re.compile(r"\b(\d+)\s*(?:ct|count|pk|pack)\b", re.I)
_BAG = re.compile(r"\bbag\b", re.I)
_SPANISH = re.compile(
    r"\b(?:crema espesa|base de pollo|jugo de naranja|huevos?|leche)\b",
    re.I,
)

HOUSE_BRANDS = (
    "member's mark",
    "members mark",
    "kirkland signature",
    "kirkland",
    "great value",
    "good & gather",
)
VENDOR_TAILS = (
    "stan's coffee",
    "stan's",
    "stans",
    "sam's club",
    "sams club",
    "chef's warehouse",
    "restaurant depot",
    "gordon food service",
    "webstaurantstore",
    "publix",
    "costco",
)
OCR_FIXES = (
    (re.compile(r"\bco\s+e\b", re.I), "coffee"),
    (re.compile(r"\bwb\b", re.I), "beans"),
    (re.compile(r"\bunsl\b", re.I), ""),
    (re.compile(r"\breserve\b", re.I), "Reserve"),
)
DROP_TOKENS = {
    "ea",
    "each",
    "n",
    "x",
    "pk",
    "cs",
    "cs.",
    "fl",
    "oz",
    "floz",
    "case",
    "'",
    "‘",
    "’",
}
SMALL_WORDS = {"and", "of", "with", "the", "a", "an", "in"}


def _title(text: str) -> str:
    words = []
    for raw in text.split():
        token = raw.strip("-/")
        if not token:
            continue
        lower = token.lower()
        if lower in SMALL_WORDS and words:
            words.append(lower)
        elif token.isupper() and len(token) <= 3:
            words.append(token)
        else:
            words.append(token[:1].upper() + token[1:])
    return " ".join(words)


def _strip_brands(text: str) -> str:
    lowered = text
    for brand in HOUSE_BRANDS + VENDOR_TAILS:
        lowered = re.sub(rf"\b{re.escape(brand)}\b", " ", lowered, flags=re.I)
    return " ".join(lowered.split())


def _enrich(name: str) -> str:
    lower = name.lower()
    if "hoagie" in lower and "roll" not in lower:
        name = f"{name} Rolls"
    words = name.split()
    rest = []
    has_coffee = False
    has_beans = False
    for word in words:
        token = word.lower()
        if token in {"coffee"}:
            has_coffee = True
            continue
        if token in {"bean", "beans"}:
            has_beans = True
            continue
        rest.append(word)
    if "decaf" in lower:
        has_coffee = True
        has_beans = True
    if has_coffee and not has_beans and "ground" not in lower:
        has_beans = True
    if has_coffee:
        rest.append("Coffee")
    if has_beans:
        rest.append("Beans")
    return " ".join(rest)


def _qty_text(qty: Decimal) -> str:
    text = format(qty, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _pack_bits(raw: str, pack_qty: Decimal | None = None, pack_unit: str = "") -> str:
    bits: list[str] = []
    inch = _INCH.search(raw or "")
    if inch:
        bits.append(f'{inch.group(1)}"')
    cleaned = _QTY_TAIL.sub("", raw or "")
    qty, unit = parse_pack(cleaned)
    if pack_qty and pack_unit and (qty <= 0 or not unit):
        qty, unit = Decimal(str(pack_qty)), pack_unit
    count = _COUNT.search(raw or "")
    if qty > 0 and unit and unit not in {"each", "ct"}:
        unit_label = {"floz": "fl oz", "dozen": "dozen"}.get(unit, unit)
        amount = f"{_qty_text(qty)} {unit_label}"
        if _BAG.search(raw or "") and "bag" not in amount:
            amount = f"{amount} bag"
        bits.append(amount)
    elif count:
        bits.append(f"{count.group(1)} count")
    elif pack_unit in {"each", "ct"} and pack_qty and Decimal(str(pack_qty)) > 1:
        bits.append(f"{_qty_text(Decimal(str(pack_qty)))} count")
    # unique, keep order
    seen: set[str] = set()
    out = []
    for bit in bits:
        key = bit.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(bit)
    return ", ".join(out)


def pretty_item(raw: str, pack_qty: Decimal | int | float | None = None, pack_unit: str = "") -> tuple[str, str]:
    """Return (display name, pack label) from a vendor/OCR description."""
    text = str(raw or "").replace("“", '"').replace("”", '"').replace("–", "-")
    text = _QTY_TAIL.sub("", text)
    text = _SKU_TOKEN.sub(" ", text)
    text = _MONEY_TAIL.sub("", text)
    text = _LEADING_CODES.sub("", text)
    text = _SPANISH.sub(" ", text)
    for pattern, repl in OCR_FIXES:
        text = pattern.sub(repl, text)
    text = _strip_brands(text)
    pack = _pack_bits(str(raw or ""), None if pack_qty is None else Decimal(str(pack_qty)), pack_unit)
    text = _INCH.sub(" ", text)
    text = _COUNT.sub(" ", text)
    text = _BAG.sub(" ", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:lb|lbs|oz|floz|gal|qt|ct|pk|pack|bag)s?\b", " ", text, flags=re.I)
    text = _TRAILING_INT.sub("", text)
    tokens = []
    for part in re.split(r"[^\w&/+]+", text):
        token = part.strip()
        if not token or token.lower() in DROP_TOKENS:
            continue
        if token.isdigit() and len(token) <= 4:
            continue
        if re.fullmatch(r"\d+\.\d+", token):
            continue
        tokens.append(token)
    name = _enrich(_title(" ".join(tokens)))
    name = re.sub(r"\bCoffee Coffee\b", "Coffee", name)
    name = re.sub(r"\bBeans Beans\b", "Beans", name)
    name = re.sub(r"\bRolls Rolls\b", "Rolls", name)
    if len(re.findall(r"[A-Za-z]{4,}", name)) < 1 or re.match(r"^[A-Z]?\d{2,}\b", name):
        return "", pack
    return name[:80].strip(" -"), pack


def looks_like_vendor_noise(raw: str) -> bool:
    text = str(raw or "")
    if re.search(r"\d+\.\d{2}", text) and len(re.findall(r"[A-Za-z]{4,}", text)) <= 1:
        return True
    if re.match(r"^\d{3,}\b", text) and re.search(r"\d+\.\d{2}", text):
        return True
    return False
