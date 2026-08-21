from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.collector import extract_rendered_prices, ingest_collected_items
from app.db import SessionLocal
from app.geo import HOME_MARKET, miles_between
from app.main import app
from app.models import Product, PurchasePrice
from app.purchasing import GAP_PCT_THRESHOLD, classify_trip, product_comparison


def test_bonita_to_estero_is_a_local_drive():
    # Costco Estero vs Survey Cafe / Bonita Springs
    miles = miles_between(26.3398, -81.7787, 26.4305, -81.8103)
    assert miles < 15
    assert HOME_MARKET.startswith("Bonita Springs")


def test_json_ld_extractor_reads_rendered_butter():
    html = """
    <html><body>
    <script type="application/ld+json">
    {"@type":"Product","name":"Unsalted Butter 4 lb","sku":"123","offers":{"@type":"Offer","price":"19.96","priceCurrency":"USD"}}
    </script>
    </body></html>
    """
    items = extract_rendered_prices(html)
    assert items
    assert items[0]["name"].startswith("Unsalted Butter")
    assert items[0]["price"] == Decimal("19.96")


def test_extension_ingest_records_sams_butter_as_high_confidence():
    db = SessionLocal()
    try:
        out = ingest_collected_items(
            db,
            {
                "supplier": "Sam's Club",
                "store": "Fort Myers",
                "source": "extension",
                "miles": 16,
                "items": [
                    {"name": "Member's Mark Unsalted Sweet Cream Butter Block", "pack": "1 lb., 4 ct.", "price": "19.96"}
                ],
            },
        )
        assert out["recorded"] == 1
        butter = db.query(Product).filter(Product.sku == "BUTTER").one()
        row = (
            db.query(PurchasePrice)
            .filter_by(product_id=butter.id, source="extension")
            .one()
        )
        assert row.unit_cost_compare == Decimal("4.99")
        assert row.confidence == Decimal("0.950")
        card = product_comparison(db, butter)
        assert any(offer.source == "extension" for offer in card["offers"])
    finally:
        db.close()


def test_far_open_prices_quote_is_not_worth_driving():
    db = SessionLocal()
    try:
        ingest_collected_items(
            db,
            {
                "supplier": "Publix Orlando",
                "store": "Orlando",
                "source": "open_prices",
                "miles": 150,
                "items": [{"name": "Unsalted Butter 1 lb", "pack": "1 lb", "price": "3.10"}],
            },
        )
        butter = db.query(Product).filter(Product.sku == "BUTTER").one()
        card = product_comparison(db, butter)
        orlando = next(row for row in card["offers"] if row.supplier.name == "Publix Orlando")
        assert classify_trip(orlando, Decimal("20"), Decimal("80")) == "skip"
        assert card["current"].supplier.name == "Chef's Warehouse"
        # Cheapest pack may be Orlando $3.10, but it is too far to recommend.
        if card["cheapest"].supplier.name == "Publix Orlando":
            assert card["recommend"] == "stay"
            assert card["trip_class"] == "skip"
    finally:
        db.close()


def test_eight_percent_and_twenty_five_dollars_still_switch_costco():
    db = SessionLocal()
    try:
        butter = db.query(Product).filter(Product.sku == "BUTTER").one()
        card = product_comparison(db, butter)
        assert card["gap_pct"] >= GAP_PCT_THRESHOLD
        assert card["recommend"] == "switch"
        assert card["trip_class"] == "go"
    finally:
        db.close()


def test_collector_page_and_ingest_api():
    with TestClient(app) as client:
        page = client.get("/collector")
        assert page.status_code == 200
        assert "Price Collector" in page.text
        assert "Restaurant Price Collector" in page.text
        assert "BROWSER EXTENSION" in page.text
        assert "Open Prices" in page.text
        assert "not n8n" in page.text
        assert "8088" in page.text
        assert "5678" in page.text
        assert 'id="cellar-api-key"' in page.text
        assert ">test<" in page.text
        ping_denied = client.get("/api/prices/ping")
        assert ping_denied.status_code == 401
        ping_ok = client.get("/api/prices/ping", headers={"X-API-Key": "test"})
        assert ping_ok.status_code == 200
        assert ping_ok.json() == {"ok": True, "app": "cellar"}
        denied = client.post("/api/prices/collect", json={"supplier": "Sam's Club", "items": []})
        assert denied.status_code == 401
        ok = client.post(
            "/api/prices/collect",
            headers={"X-API-Key": "test"},
            json={
                "supplier": "Costco",
                "source": "extension",
                "store": "Estero",
                "miles": 11,
                "items": [{"name": "Kirkland unsalted butter 4 lb", "pack": "4 lb", "price": 18.99}],
            },
        )
        assert ok.status_code == 200
        assert ok.json()["recorded"] == 1
        purchasing = client.get("/purchasing")
        assert "Worth changing" in purchasing.text or "Maybe" in purchasing.text
        assert "Bonita Springs" in purchasing.text
