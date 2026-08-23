"""Drink boards: coffee, wine, beer, soda. Rankings come from Square, not taste scores."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.sales_report import category_board

DRINKS = {
    "coffee": {
        "slug": "coffee",
        "label": "Coffee",
        "categories": ("Coffee",),
        "blurb": "Which coffee sells. This is Square tickets, not a taste contest.",
    },
    "wine": {
        "slug": "wine",
        "label": "Wine",
        "categories": ("Wine",),
        "blurb": "Wine by the glass and bottle from Square. The cellar list is names only.",
    },
    "beer": {
        "slug": "beer",
        "label": "Beer",
        "categories": ("Beer", "Cocktails"),
        "blurb": "Beer first. Cocktails sit here so they are not lost in food.",
    },
    "soda": {
        "slug": "soda",
        "label": "Soda",
        "categories": ("Soda & water", "Tea & juice"),
        "blurb": "Soda, water, tea, and juice from Square.",
    },
}

DRINK_ORDER = ("coffee", "wine", "beer", "soda")


def drink_spec(slug: str) -> dict | None:
    return DRINKS.get(slug)


def drinks_overview(db: Session, start: date, end: date) -> list[dict]:
    cards = []
    for slug in DRINK_ORDER:
        spec = DRINKS[slug]
        board = category_board(db, start, end, spec["categories"], limit=3)
        cards.append({**spec, "board": board})
    return cards


def drink_board(db: Session, slug: str, start: date, end: date) -> dict | None:
    spec = drink_spec(slug)
    if spec is None:
        return None
    return {**spec, "board": category_board(db, start, end, spec["categories"], limit=40)}
