from __future__ import annotations

import re

from sqlalchemy.orm import Session, joinedload

from app.models import Product, Recipe, SellableItem

JUNK = {
    "a",
    "an",
    "and",
    "btg",
    "btl",
    "bottle",
    "de",
    "du",
    "glass",
    "la",
    "large",
    "le",
    "of",
    "reg",
    "regular",
    "small",
    "the",
    "with",
}


def normalize_menu_name(name: str) -> str:
    text = str(name or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [part for part in text.split() if part and part not in JUNK]
    return " ".join(tokens)


def name_score(left: str, right: str) -> float:
    a = normalize_menu_name(left)
    b = normalize_menu_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        shorter = a if len(a) <= len(b) else b
        if len(shorter) >= 6 or len(shorter.split()) >= 2:
            return 0.88
        return 0.4
    ta, tb = set(a.split()), set(b.split())
    overlap = ta & tb
    if not overlap:
        return 0.0
    if len(overlap) < 2 and max(len(ta), len(tb)) > 2:
        return 0.0
    return len(overlap) / len(ta | tb)


def _best(name: str, candidates: list, attr: str, threshold: float):
    scored = []
    for item in candidates:
        score = name_score(name, getattr(item, attr))
        if score >= threshold:
            scored.append((score, item))
    if not scored:
        return None
    scored.sort(key=lambda row: row[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0] and scored[0][0] < 0.95:
        return None
    return scored[0][1]


def _apply_wine_pour(item: SellableItem, product: Product) -> None:
    profile = product.wine
    if not profile:
        return
    lowered = item.name.lower()
    if "bottle" in lowered or "btl" in lowered:
        item.serving_qty = profile.bottle_size_ml
    else:
        item.serving_qty = profile.glass_pour_ml
    item.serving_unit = "ml"
    if item.costing_group in ("", "food", "other"):
        item.costing_group = "wine"


def match_sellables(db: Session) -> dict:
    recipes = db.query(Recipe).all()
    wines = (
        db.query(Product)
        .options(joinedload(Product.wine))
        .filter(Product.category == "wine")
        .all()
    )
    items = (
        db.query(SellableItem)
        .filter((SellableItem.recipe_id.is_(None)) | (SellableItem.product_id.is_(None)))
        .all()
    )
    linked_recipes = 0
    linked_wines = 0
    for item in items:
        if item.product_id is None:
            wine = _best(item.name, wines, "name", 0.88)
            if wine:
                item.product_id = wine.id
                _apply_wine_pour(item, wine)
                linked_wines += 1
        if item.recipe_id is None and item.product_id is None:
            recipe = _best(item.name, recipes, "name", 0.88)
            if recipe:
                item.recipe_id = recipe.id
                linked_recipes += 1
    db.commit()
    return {"recipes": linked_recipes, "wines": linked_wines}
