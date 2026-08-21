from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.ingest import coerce_money, ingest_paperless_doc, ingest_recipes, ingest_sales, parse_invoice_amount
from app.main import app
from app.matching import match_sellables, name_score, normalize_menu_name
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
        db.close()
