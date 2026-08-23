from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.ingest import coerce_money, ingest_paperless_doc, ingest_recipes, ingest_sales, parse_invoice_amount
from app.main import app
from app.matching import link_sellable, match_sellables, name_score, normalize_menu_name, suggest_matches
from app.models import Invoice, SellableItem


def test_chefs_florida_llc_maps_to_chefs_warehouse():
    with TestClient(app):
        db = SessionLocal()
        ingest_paperless_doc(
            db,
            {
                "id": "cw-fl-1",
                "title": "Weekly produce $88.10",
                "correspondent": "The Chefs' Warehouse of Florida, LLC",
                "total": "88.10",
            },
        )
        invoice = db.query(Invoice).filter(Invoice.paperless_id == "cw-fl-1").one()
        assert invoice.supplier is not None
        assert invoice.supplier.name == "Chef's Warehouse"
        db.close()


def test_parse_invoice_amount_prefers_dollar_and_total_labels():
    assert parse_invoice_amount("FPL Bill $187.42") == Decimal("187.42")
    assert parse_invoice_amount("Invoice Total: 1,204.50 due 12/01") == Decimal("1204.50")
    assert parse_invoice_amount("Packing list 2024") == Decimal("0")
    assert coerce_money("$88.10") == Decimal("88.10")
    assert coerce_money(12.5) == Decimal("12.50")
    assert coerce_money("34008624849.68") == Decimal("0")
    assert coerce_money("2000000") == Decimal("0")
    assert coerce_money("4103.23") == Decimal("4103.23")
    from app.ingest import should_replace_total

    assert should_replace_total(Decimal("1.45"), coerce_money("34008624849.68")) is False
    assert should_replace_total(Decimal("2000000.00"), Decimal("0")) is True


def test_parse_invoice_amount_skips_sams_cash_and_reads_receipt_total():
    from app.ingest import should_replace_total

    sams = """
    SUBTOTAL 52.66
    TOTAL 53.68
    DEBIT TEND 53.68
    CHANGE DUE 0.00
    You earned $1.08 in Sam's Cash
    """
    assert parse_invoice_amount(sams) == Decimal("53.68")
    depot = """
    SUBTOTAL $239.39
    TOTAL TAX $0.00
    TOTAL $239 39
    MASTERCARD $239.39
    CHANGE
    BALANCE $0.00
    """
    assert parse_invoice_amount(depot) == Decimal("239.39")
    wine = "Subtotal USD 180.60 Sales Tax (0.0%) 0.00 Payment/Credit USD 0.00"
    assert parse_invoice_amount(wine) == Decimal("180.60")
    purchase = "14 6 .5 8 T O T A L P U R C H A S E"
    assert parse_invoice_amount(purchase) == Decimal("146.58")
    assert parse_invoice_amount("2% Milk 12.08  103.23\nTax 0.00\n103.23") == Decimal("103.23")
    assert should_replace_total(Decimal("1.08"), Decimal("53.68")) is True
    assert should_replace_total(Decimal("189.60"), Decimal("90.00")) is False


def test_zero_invoice_is_updated_when_title_has_amount():
    with TestClient(app):
        db = SessionLocal()
        first = ingest_paperless_doc(db, {"id": "pl-1", "title": "Vestis weekly", "total": 0})
        assert first["status"] == "created"
        again = ingest_paperless_doc(
            db,
            {"id": "pl-1", "title": "Vestis weekly $240.00", "total": 0, "content": "Amount due 240.00"},
        )
        assert again["status"] == "updated"
        from app.models import Invoice

        invoice = db.get(Invoice, first["invoice_id"])
        assert invoice.total == Decimal("240.00")
        db.close()


def test_sams_receipt_records_every_pack_not_just_eggs():
    with TestClient(app):
        db = SessionLocal()
        result = ingest_paperless_doc(
            db,
            {
                "id": "sams-full-1",
                "title": "Sam's Club receipt",
                "correspondent": "Sam's Club",
                "invoice_type": "food",
                "content": """
                Member's Mark Heavy Whipping Cream 64 fl. oz.
                Qty 8
                $46.16
                Pineapple
                $3.37/ea
                Qty 4
                $13.48
                Large Eggs 15 dozen
                Qty 3
                $82.26
                """,
            },
        )
        from app.models import InvoiceLine, PurchasePrice

        lines = db.query(InvoiceLine).filter(InvoiceLine.invoice_id == result["invoice_id"]).all()
        names = " ".join(line.raw_description for line in lines)
        assert "Cream" in names
        assert "Pineapple" in names
        prices = db.query(PurchasePrice).filter(PurchasePrice.invoice_id == result["invoice_id"]).all()
        assert len(prices) >= 3
        pineapple = next(line for line in lines if "Pineapple" in line.raw_description)
        pineapple_price = next(row for row in prices if row.invoice_line_id == pineapple.id)
        assert pineapple_price.unit_cost_compare == Decimal("3.37")
        assert pineapple.product is not None
        assert pineapple.product.name == "Pineapple"
        db.close()


def test_insurance_email_is_not_a_two_million_food_invoice():
    from app.ingest import scrub_junk_invoices
    from app.sync import infer_invoice_type

    assert infer_invoice_type("[No action required] Congrats! Your business is covered with General Liability") == "ignore"
    with TestClient(app):
        db = SessionLocal()
        junk = ingest_paperless_doc(
            db,
            {
                "id": "ins-1",
                "title": "[No action required] Your General Liability policy will renew",
                "total": "2000000.00",
                "invoice_type": "food",
            },
        )
        invoice = db.get(Invoice, junk["invoice_id"])
        assert invoice.invoice_type == "ignore"
        assert invoice.total == Decimal("0")
        invoice.invoice_type = "food"
        invoice.total = Decimal("2000000.00")
        db.commit()
        assert scrub_junk_invoices(db)["updated"] == 1
        db.refresh(invoice)
        assert invoice.invoice_type == "ignore"
        assert invoice.total == Decimal("0")
        db.close()


def test_bilingual_mealie_names_match_square_english():
    assert normalize_menu_name("Avocado Toast · Tostada de Aguacate") == "avocado toast"
    assert name_score("Avocado Toast", "Avocado Toast · Tostada de Aguacate") == 1.0
    assert normalize_menu_name("Sauvignon Blanc glass") == "sauvignon blanc"
    assert name_score("House Burger", "House Burger") == 1.0
    with TestClient(app):
        db = SessionLocal()
        ingest_sales(
            db,
            [
                {
                    "sold_at": "2026-08-01T12:00:00",
                    "name": "House Burger",
                    "qty": 2,
                    "unit_price": 18,
                    "revenue": 36,
                    "square_order_id": "sq-b1",
                    "square_line_id": "sq-b1-l1",
                    "square_item_id": "sq-burger",
                    "costing_group": "food",
                },
                {
                    "sold_at": "2026-08-01T12:00:00",
                    "name": "Sauvignon Blanc",
                    "qty": 1,
                    "unit_price": 11,
                    "revenue": 11,
                    "square_order_id": "sq-w1",
                    "square_line_id": "sq-w1-l1",
                    "square_item_id": "sq-sb",
                    "costing_group": "food",
                },
            ],
        )
        ingest_recipes(
            db,
            [
                {
                    "name": "House Burger",
                    "mealie_id": "burger-1",
                    "lines": [{"name": "Beef", "qty": 200, "unit": "g"}],
                }
            ],
        )
        result = match_sellables(db)
        assert result["recipes"] >= 1
        assert result["wines"] >= 1
        burger = db.query(SellableItem).filter(SellableItem.square_item_id == "sq-burger").one()
        assert burger.recipe_id is not None
        wine_item = db.query(SellableItem).filter(SellableItem.square_item_id == "sq-sb").one()
        assert wine_item.product_id is not None
        assert wine_item.serving_unit == "ml"
        leftover = SellableItem(name="House Burger lunch", costing_group="food", selling_price=Decimal("18"))
        db.add(leftover)
        db.commit()
        rows = suggest_matches(db)
        burger_row = next(row for row in rows if row["item"].name == "House Burger lunch")
        assert burger_row["suggestions"]
        assert burger_row["suggestions"][0]["kind"] == "recipe"
        linked = link_sellable(db, leftover.id, "recipe", burger.recipe_id)
        assert linked["ok"] is True
        db.refresh(leftover)
        assert leftover.recipe_id == burger.recipe_id
        db.close()
