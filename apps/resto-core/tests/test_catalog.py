from datetime import date
from html import unescape
from pathlib import Path
from decimal import Decimal

from fastapi.testclient import TestClient

from app.catalog import CATALOGS, parse_webstaurant, record_catalog_quote, scan_catalogs
from app.db import SessionLocal
from app.main import app
from app.models import Product, PurchasePrice, Supplier
from app.purchasing import match_canonical_product, product_comparison
from app.units import comparable_cost, parse_pack

FIXTURE = Path(__file__).parent / "fixtures" / "webstaurant-butter.html"


def test_webstaurant_parser_finds_36lb_case():
    html = FIXTURE.read_text(encoding="utf-8", errors="replace")
    quotes = parse_webstaurant(html)
    grassland = next(q for q in quotes if "Grassland" in q["description"])
    vegan = next(q for q in quotes if "Violife" in q["description"])
    assert grassland["pack_qty"] == Decimal("36")
    assert grassland["pack_unit"] == "lb"
    assert parse_pack(grassland["description"]) == (Decimal("36"), "lb")
    cost = comparable_cost(grassland["pack_price"], grassland["pack_qty"], grassland["pack_unit"], "lb")
    assert cost == Decimal("3.86")
    assert vegan["pack_qty"] > 0
    assert "vegan" in vegan["description"].lower()


def test_vegan_butter_is_not_canonical_butter():
    db = SessionLocal()
    try:
        product, _score = match_canonical_product(
            db,
            "Violife Plant-Based Vegan Butter Sticks - 8 oz. - 36/Case",
        )
        assert product is None or product.sku != "BUTTER"
        real, score = match_canonical_product(
            db,
            "Grassland Unsalted Grade AA Butter Solid - 1 lb. - 36/Case",
        )
        assert real is not None
        assert real.sku == "BUTTER"
        assert score > 0
    finally:
        db.close()


def test_catalog_quote_sits_beside_paid_price():
    db = SessionLocal()
    try:
        butter = db.query(Product).filter(Product.sku == "BUTTER").one()
        web = db.query(Supplier).filter_by(name="WebstaurantStore").one_or_none()
        if web is None:
            web = Supplier(
                name="WebstaurantStore",
                category="food",
                default_invoice_type="food",
            )
            db.add(web)
            db.flush()
        html = FIXTURE.read_text(encoding="utf-8", errors="replace")
        grassland = next(q for q in parse_webstaurant(html) if "Grassland" in q["description"])
        record_catalog_quote(db, butter, web, grassland, date.today())
        db.commit()
        listed = (
            db.query(PurchasePrice)
            .filter_by(product_id=butter.id, source="catalog")
            .one()
        )
        assert listed.unit_cost_compare == Decimal("3.86")
        card = product_comparison(db, butter)
        assert card is not None
        assert card["current"].supplier.name == "Chef's Warehouse"
        assert card["current"].source != "catalog"
        assert card["cheapest"].supplier.name == "WebstaurantStore"
        assert card["cheapest"].source == "catalog"
        assert card["recommend"] == "consider"
        assert any(row.source == "catalog" for row in card["market"])
    finally:
        db.close()


def test_scan_catalogs_uses_fixture_html(monkeypatch):
    html = FIXTURE.read_text(encoding="utf-8", errors="replace")
    assert len(html) >= 2000

    class FakeResp:
        status_code = 200
        text = html

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def get(self, url, headers=None):
            return FakeResp()

    monkeypatch.setattr("app.catalog.httpx.Client", FakeClient)
    db = SessionLocal()
    try:
        out = scan_catalogs(db)
        assert out["quotes"] >= 1
        assert not any(item.get("error") for item in out["sources"])
        butter = db.query(Product).filter(Product.sku == "BUTTER").one()
        row = (
            db.query(PurchasePrice)
            .filter_by(source="catalog", product_id=butter.id)
            .one()
        )
        assert row.supplier.name == "WebstaurantStore"
        assert row.unit_cost_compare == Decimal("3.86")
        vegan_rows = (
            db.query(PurchasePrice)
            .filter(PurchasePrice.raw_description.ilike("%vegan%"))
            .count()
        )
        assert vegan_rows == 0
        assert (
            db.query(PurchasePrice)
            .filter_by(source="catalog", product_id=butter.id)
            .count()
            == 1
        )
    finally:
        db.close()


def test_lexicon_lists_blocked_sites():
    labels = {c["label"] for c in CATALOGS}
    assert "Sam's Club" in labels
    assert "WebstaurantStore" in labels
    assert "Restaurant Depot" in labels
    assert "Publix" in labels
    assert "Walmart" in labels
    fetchable = [c for c in CATALOGS if c.get("parser") == "webstaurant"]
    assert len(fetchable) == 1


def test_purchasing_page_shows_catalog_lexicon():
    with TestClient(app) as client:
        page = client.get("/purchasing")
        assert page.status_code == 200
        text = unescape(page.text)
        assert "Bonita Springs" in text
        assert "WebstaurantStore" in text
        assert "Sam's Club" in text
        assert "Daily refresh" in text
        assert "receipts + extension" in text or "Sam's Club" in text
        assert "BROWSER EXTENSION" in text
        assert "Open Prices" in text
