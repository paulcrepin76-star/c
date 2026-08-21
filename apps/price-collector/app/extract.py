from __future__ import annotations

import json
import re
from decimal import Decimal
from urllib.parse import quote_plus, quote

CAPTCHA_HINTS = (
    "px-captcha",
    "perimeterx",
    "px-blocked",
    "cf-challenge",
    "challenge-platform",
    "hcaptcha",
    "g-recaptcha",
    "verify you are human",
    "confirm you are a human",
    "attention required",
    "access denied",
    "are you a robot",
    "bot detection",
)
LOGIN_HINTS = (
    "forgot password",
    "reset password",
    "one-time code",
    "verification code",
    "two-step",
    "two factor",
    "2-step verification",
)
LOGIN_URL_BITS = ("/login", "/signin", "/sign-in", "/logon", "auth0.com", "okta.com")
NAME_KEYS = ("name", "title", "productName", "description", "alt")
PRICE_KEYS = ("price", "salePrice", "currentPrice", "finalPrice", "listPrice", "amount", "lowPrice")
SKU_KEYS = ("sku", "itemNumber", "itemId", "item_id", "productId", "upc", "gtin", "gtin13")


def classify_wall(url: str, html: str, text: str) -> str | None:
    blob = f"{url}\n{html}\n{text}".lower()
    if any(hint in blob for hint in CAPTCHA_HINTS):
        return "captcha"
    url_l = (url or "").lower()
    if any(bit in url_l for bit in LOGIN_URL_BITS):
        return "login"
    if "password" in text.lower() and any(word in text.lower() for word in ("sign in", "log in", "login")):
        return "login"
    if any(hint in text.lower() for hint in LOGIN_HINTS) and "password" in text.lower():
        return "login"
    return None


def _price_amount(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in PRICE_KEYS:
            if value.get(key) not in (None, ""):
                return _price_amount(value.get(key))
        return None
    try:
        amount = float(Decimal(str(value).replace("$", "").replace(",", "").strip()))
    except Exception:  # noqa: BLE001
        return None
    return amount if amount > 0 else None


def _first_str(obj: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, dict) and "name" in value:
            value = value.get("name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def walk_products(payload, found: list[dict] | None = None, depth: int = 0) -> list[dict]:
    if found is None:
        found = []
    if depth > 10 or len(found) >= 80:
        return found
    if isinstance(payload, list):
        for item in payload:
            walk_products(item, found, depth + 1)
        return found
    if not isinstance(payload, dict):
        return found
    name = _first_str(payload, NAME_KEYS)
    offers = payload.get("offers")
    price = _price_amount(payload.get("salePrice") or payload.get("finalPrice") or payload.get("price"))
    if price is None and isinstance(offers, dict):
        price = _price_amount(offers)
    elif price is None and isinstance(offers, list) and offers:
        price = _price_amount(offers[0] if isinstance(offers[0], dict) else None)
    if name and price is not None and len(name) >= 4:
        list_price = _price_amount(payload.get("listPrice") or payload.get("regularPrice")) or price
        found.append(
            {
                "name": name[:240],
                "pack": str(payload.get("size") or payload.get("pack") or payload.get("packSize") or "")[:120],
                "price": price,
                "regular_price": list_price,
                "promo_price": price if list_price and price < list_price else None,
                "sku": _first_str(payload, SKU_KEYS)[:80],
                "upc": _first_str(payload, ("upc", "gtin", "gtin13"))[:80],
                "brand": _first_str(payload, ("brand", "brandName"))[:120],
                "url": str(payload.get("url") or payload.get("link") or "")[:400],
                "discount": bool(list_price and price < list_price),
                "available": payload.get("available", payload.get("inStock", True)) is not False,
            }
        )
    for value in payload.values():
        if isinstance(value, (dict, list)):
            walk_products(value, found, depth + 1)
    return found


def products_from_json_text(raw: str) -> list[dict]:
    text = (raw or "").strip()
    if len(text) < 8 or text[0] not in "{[":
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    return walk_products(payload)


def products_from_html(html: str) -> list[dict]:
    found: list[dict] = []
    for raw in re.findall(r"<script[^>]*>(.*?)</script>", html or "", re.S | re.I):
        found.extend(products_from_json_text(raw.strip()))
    seen: set[str] = set()
    unique = []
    for item in found:
        key = f"{item.get('sku') or item.get('name')}|{item.get('price')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def search_url(source: dict, query: str) -> str:
    template = source.get("search_url") or ""
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    return template.replace("{query}", quote_plus(query)).replace("{slug}", quote(slug))


def matches_watch(item: dict, needles: list[str]) -> bool:
    if not needles:
        return True
    blob = f"{item.get('name')} {item.get('pack')} {item.get('sku')} {item.get('upc')}".lower()
    return any(needle and str(needle).lower() in blob for needle in needles)
