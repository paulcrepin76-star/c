from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.ingest import extract_invoice_lines, ingest_paperless_doc
from app.main import app
from app.models import Product, PurchasePrice, Supplier
from app.purchasing import STAY_THRESHOLD, match_canonical_product, product_comparison, purchasing_board
from app.units import comparable_cost, parse_pack


def test_pack_normalization_never_compares_sticker_price():
    assert parse_pack("Butter unsalted 36 lb case") == (Decimal("36"), "lb")
    assert parse_pack("Butter 4 lb pack") == (Decimal("4"), "lb")
    assert parse_pack("BUTTER UNSLT 36/1 LB 5.600 201.60") == (Decimal("36"), "lb")
    assert parse_pack("Member's Mark Unsalted Sweet Cream Butter Block, 1 lb., 4 ct.") == (Decimal("4"), "lb")
    assert parse_pack("Member's Mark Unsalted Sweet Cream Butter Block, 1 lb., 4 ct. Qty 4") == (Decimal("16"), "lb")
    assert parse_pack("Large Eggs 15 dozen Qty 3") == (Decimal("45"), "dozen")
    assert parse_pack("Member's Mark Vitamin D Whole Milk, 1 gal. Qty 3") == (Decimal("3"), "gal")
    assert parse_pack("Grassland Unsalted Grade AA Butter Solid - 1 lb. - 36/Case") == (Decimal("36"), "lb")
    assert comparable_cost(Decimal("201.60"), Decimal("36"), "lb", "lb") == Decimal("5.60")
    assert comparable_cost(Decimal("19.96"), Decimal("4"), "lb", "lb") == Decimal("4.99")
    assert comparable_cost(Decimal("47.88"), Decimal("15"), "dozen", "each") == Decimal("0.266")
    assert comparable_cost(Decimal("32.96"), Decimal("16"), "lb", "lb") == Decimal("2.06")


def test_butter_board_picks_costco_and_keeps_chefs_as_current():
    db = SessionLocal()
    butter = db.query(Product).filter(Product.sku == "BUTTER").one()
    card = product_comparison(db, butter)
    assert card is not None
    assert card["current"].supplier.name == "Chef's Warehouse"
    assert card["current"].unit_cost_compare == Decimal("5.60")
    assert card["cheapest"].supplier.name == "Costco"
    assert card["cheapest"].unit_cost_compare == Decimal("4.99")
    assert card["gap"] == Decimal("0.61")
    assert card["usage"] == Decimal("74")
    assert card["monthly"] == Decimal("45.14")
    assert card["recommend"] == "switch"
    names = {item["recipe"]: item["delta"] for item in card["impacts"]}
    assert names["Croissant"] == Decimal("-0.07")
    assert names["French Toast"] == Decimal("-0.05")
    db.close()


def test_small_monthly_saving_says_stay():
    db = SessionLocal()
    eggs = db.query(Product).filter(Product.sku == "EGG").one()
    card = product_comparison(db, eggs)
    assert card is not None
    assert card["current"].supplier.name == "Sam's Club"
    assert card["cheapest"].supplier.name == "Costco"
    assert card["net"] < STAY_THRESHOLD
    assert card["recommend"] == "stay"
    db.close()


def test_peanut_butter_is_not_butter():
    db = SessionLocal()
    product, score = match_canonical_product(db, "Peanut butter 5 lb 12.99")
    assert product is None or product.sku != "BUTTER"
    veggies, veg_score = match_canonical_product(
        db,
        "Veggies: Caramelized onions, spinach, tomato, roasted pepper, grilled mushrooms +$1.50 each",
    )
    assert veggies is None or veggies.sku != "EGG"
    yogurt, yogurt_score = match_canonical_product(db, "Member's Mark Honey Vanilla Whole Milk Greek Yogurt, 48 oz. Qty 6")
    assert yogurt is None or yogurt.sku != "MILK"
    db.close()


def test_sams_multiline_receipt_normalizes_butter():
    blob = """
    Member's Mark Unsalted Sweet Cream Butter Block, 1 lb., 4 ct.
    $2.06/lb
    Qty 4
    $32.96
    Strawberries, 2 lbs.
    $2.49/lb
    Qty 10
    $49.70
    Invoice Total 214.59
    """
    lines = extract_invoice_lines(blob)
    butter = next(item for item in lines if "Butter" in item["description"])
    assert butter["qty"] == Decimal("16")
    assert butter["unit"] == "lb"
    assert butter["line_total"] == Decimal("32.96")
    assert comparable_cost(butter["line_total"], butter["qty"], butter["unit"], "lb") == Decimal("2.06")
    blob = """
    Chef's Warehouse
    BUTTER UNSLT AA 36/1 LB 5.60 201.60
    PEANUT BUTTER 5 LB 12.99
    Invoice Total 214.59
    """
    lines = extract_invoice_lines(blob)
    descriptions = " ".join(item["description"] for item in lines)
    assert "36" in descriptions or any(item["qty"] == Decimal("36") for item in lines)
    assert all("Invoice Total" not in item["description"] for item in lines)


def test_ocr_invoice_records_immutable_price_history():
    with TestClient(app):
        db = SessionLocal()
        first = ingest_paperless_doc(
            db,
            {
                "id": "cw-ocr-1",
                "title": "Chef's weekly",
                "correspondent": "Chef's Warehouse",
                "invoice_type": "food",
                "content": "BUTTER UNSLT 36/1 LB 201.60\nInvoice Total 201.60",
            },
        )
        assert first["status"] == "created"
        second = ingest_paperless_doc(
            db,
            {
                "id": "cw-ocr-1",
                "title": "Chef's weekly",
                "correspondent": "Chef's Warehouse",
                "invoice_type": "food",
                "content": "BUTTER UNSLT 36/1 LB 201.60\nInvoice Total 201.60",
            },
        )
        assert second["status"] == "duplicate"
        prices = db.query(PurchasePrice).filter(PurchasePrice.invoice_id == first["invoice_id"]).all()
        assert len(prices) == 1
        assert prices[0].unit_cost_compare == Decimal("5.60")
        db.close()


def test_existing_invoice_gains_canonical_ocr_lines():
    with TestClient(app):
        db = SessionLocal()
        first = ingest_paperless_doc(
            db,
            {
                "id": "cw-ocr-2",
                "title": "Chef's mixed",
                "correspondent": "Chef's Warehouse",
                "invoice_type": "food",
                "lines": [{"description": "Compressor 1 EA 2298.96", "qty": 1, "unit": "each", "line_total": "2298.96"}],
            },
        )
        assert first["status"] == "created"
        again = ingest_paperless_doc(
            db,
            {
                "id": "cw-ocr-2",
                "title": "Chef's mixed",
                "correspondent": "Chef's Warehouse",
                "invoice_type": "food",
                "content": "BUTTER UNSLT 36/1 LB 201.60\nInvoice Total 201.60",
            },
        )
        assert again["status"] == "updated"
        prices = db.query(PurchasePrice).filter(PurchasePrice.invoice_id == first["invoice_id"]).all()
        assert any(row.unit_cost_compare == Decimal("5.60") for row in prices)
        db.close()


def test_purchasing_page_and_api():
    with TestClient(app) as client:
        page = client.get("/purchasing")
        assert page.status_code == 200
        assert "Supplier price comparison" in page.text
        assert "Costco" in page.text
        assert "$4.99" in page.text
        assert "Warehouse" in page.text
        assert "$5.60" in page.text
        dairy = client.get("/purchasing?category=dairy")
        assert dairy.status_code == 200
        assert "Butter" in dairy.text
        payload = client.get("/api/purchasing", headers={"X-API-Key": "test"})
        assert payload.status_code == 200
        body = payload.json()
        assert body["cheaper_elsewhere"] >= 1
        butter = next(card for card in body["cards"] if card["product"] == "Butter")
        assert butter["best_supplier"] == "Costco"
        assert butter["current_supplier"] == "Chef's Warehouse"
        home = client.get("/")
        assert "Purchasing" in home.text
        assert 'href="/purchasing"' in home.text


def test_restaurant_depot_is_a_vendor():
    db = SessionLocal()
    depot = db.query(Supplier).filter(Supplier.name == "Restaurant Depot").one()
    assert depot.default_invoice_type == "food"
    db.close()
    with TestClient(app) as client:
        connect = client.get("/connect")
        assert "Restaurant Depot" in connect.text
