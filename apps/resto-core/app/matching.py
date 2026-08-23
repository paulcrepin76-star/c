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
    text = str(name or "").split("·")[0].lower().replace("&", " and ")
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


def rank_candidates(name: str, candidates: list, attr: str, floor: float = 0.45, limit: int = 3) -> list[tuple[float, object]]:
    scored = []
    for item in candidates:
        score = name_score(name, getattr(item, attr))
        if score >= floor:
            scored.append((score, item))
    scored.sort(key=lambda row: row[0], reverse=True)
    return scored[:limit]


def _best(name: str, candidates: list, attr: str, threshold: float):
    scored = rank_candidates(name, candidates, attr, floor=threshold, limit=2)
    if not scored:
        return None
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


def suggest_matches(db: Session, limit: int = 80) -> list[dict]:
    recipes = db.query(Recipe).order_by(Recipe.name).all()
    wines = (
        db.query(Product)
        .options(joinedload(Product.wine))
        .filter(Product.category == "wine")
        .order_by(Product.name)
        .all()
    )
    items = (
        db.query(SellableItem)
        .filter(SellableItem.recipe_id.is_(None), SellableItem.product_id.is_(None))
        .order_by(SellableItem.name)
        .limit(limit)
        .all()
    )
    rows = []
    for item in items:
        suggestions = []
        for score, wine in rank_candidates(item.name, wines, "name"):
            suggestions.append({"kind": "wine", "id": wine.id, "name": wine.name, "score": score, "label": f"Wine · {wine.name}"})
        for score, recipe in rank_candidates(item.name, recipes, "name"):
            suggestions.append({"kind": "recipe", "id": recipe.id, "name": recipe.name, "score": score, "label": f"Recipe · {recipe.name}"})
        suggestions.sort(key=lambda row: row["score"], reverse=True)
        rows.append({"item": item, "suggestions": suggestions[:3]})
    return rows


def link_sellable(db: Session, item_id: int, kind: str, target_id: int) -> dict:
    item = db.get(SellableItem, item_id)
    if item is None:
        return {"ok": False, "error": "Unknown Square item"}
    if kind == "wine":
        product = db.get(Product, target_id)
        if product is None or product.category != "wine":
            return {"ok": False, "error": "Unknown wine"}
        item.product_id = product.id
        item.recipe_id = None
        _apply_wine_pour(item, product)
    elif kind == "recipe":
        recipe = db.get(Recipe, target_id)
        if recipe is None:
            return {"ok": False, "error": "Unknown recipe"}
        item.recipe_id = recipe.id
        item.product_id = None
    else:
        return {"ok": False, "error": "Pick a recipe or a wine"}
    db.commit()
    return {"ok": True, "item": item.name, "kind": kind}
