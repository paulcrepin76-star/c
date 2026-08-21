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
    assert parse_pack("1 lb. Salted Grade AA Butter Stick Quarters - 18/Case") == (Decimal("18"), "lb")
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
    cashew, _score = match_canonical_product(db, "Bare Nut Butter Unsalted Cashew Butter 15 lb.")
    assert cashew is None or cashew.sku != "BUTTER"
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
        assert "compare" in page.text
        names = [card["product"].name for card in purchasing_board(SessionLocal())["cards"]]
        assert names == sorted(names, key=str.lower)
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
        assert "PG Fine Wines" not in connect.text
        assert "ALDI" not in connect.text


def test_faded_scan_does_not_invent_line_items():
    from app.ingest import ocr_is_usable

    faded = "AGO0000 VISA CREDIT Thank you Clu Put Join today Term publ ix il"
    assert ocr_is_usable(faded) is False
    wine = """
    PG Fine Wines
    Veuve Parisot Sparkling Brut 12/750 99.60
    Pinot Grigio Delle Venezie 12x750 90.00
    Subtotal USD 189.60
    Total USD 189.60
    """
    assert ocr_is_usable(wine) is True
    with TestClient(app):
        db = SessionLocal()
        result = ingest_paperless_doc(
            db,
            {
                "id": "faded-ticket-1",
                "title": "Scan faded ticket",
                "correspondent": None,
                "invoice_type": "food",
                "content": faded,
            },
        )
        assert result["status"] == "created"
        from app.models import InvoiceLine

        lines = db.query(InvoiceLine).filter(InvoiceLine.invoice_id == result["invoice_id"]).all()
        assert lines == []
        db.close()


def test_wine_house_and_depot_license_do_not_confuse_types():
    from app.sync import infer_invoice_type

    assert infer_invoice_type("Scan", "Wine Invoice", "PG Fine Wines") == "wine"
    assert infer_invoice_type(
        "Scan",
        "Vendor Invoice",
        "PG Fine Wines",
        "Veuve Parisot Sparkling Brut 12/750 99.60",
    ) == "wine"
    assert infer_invoice_type(
        "Scan",
        "Vendor Invoice",
        "Restaurant Depot",
        "Wine 2COP-0-BEV4606429 Beer license TOM SUNDRIED W/OIL 4LB $16.81",
    ) == "food"
    assert infer_invoice_type("fpl-0983944356-2026-08-06", "Utility Bill", "FPL Bonita Springs") == "utility"
    assert infer_invoice_type("sams-club-2026-05-24", "Vendor Invoice", "Sam's Club", "WATERMELON 6.98") == "food"
    assert infer_invoice_type("Your General Liability auto-renewal is here") == "ignore"
    assert infer_invoice_type("Quote Sphplm LLC") == "ignore"
