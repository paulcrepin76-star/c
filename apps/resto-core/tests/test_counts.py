from decimal import Decimal

from fastapi.testclient import TestClient

from app.counts import count_sheet, default_location, save_count
from app.db import SessionLocal
from app.main import app
from app.models import InventoryCount, Product, StockMove
from app.services import on_hand_base


def test_count_pages_and_partial_save():
    with TestClient(app) as client:
        hub = client.get("/inventory")
        assert hub.status_code == 200
        assert "Walk-in cooler" in hub.text
        walk = client.get("/inventory/count?location=walk-in")
        assert walk.status_code == 200
        assert "Butter" in walk.text or "Milk" in walk.text or "Eggs" in walk.text
        wine = client.get("/inventory/count?location=wine-cellar")
        assert "Sauvignon Blanc" in wine.text
        db = SessionLocal()
        try:
            product = db.query(Product).filter(Product.name == "Sauvignon Blanc").one()
            product_id = product.id
            before = on_hand_base(db, product_id)
        finally:
            db.close()
        empty = client.post("/inventory/count", data={"location": "wine-cellar", "notes": "nothing"}, follow_redirects=False)
        assert empty.status_code == 303
        saved = client.post(
            "/inventory/count",
            data={"location": "wine-cellar", "notes": "Night count", f"qty_{product_id}": "7"},
            follow_redirects=False,
        )
        assert saved.status_code == 303
        assert "/inventory/counts/" in saved.headers["location"]
        detail = client.get(saved.headers["location"])
        assert detail.status_code == 200
        assert "Sauvignon Blanc" in detail.text
        assert "7" in detail.text
        db = SessionLocal()
        try:
            after = on_hand_base(db, product_id)
            assert after == Decimal("7") * Decimal("750")
            count = db.query(InventoryCount).order_by(InventoryCount.id.desc()).first()
            assert count.location == "wine-cellar"
            assert count.notes == "Night count"
            moves = db.query(StockMove).filter(StockMove.reason == "count_adjust", StockMove.product_id == product_id).all()
            assert moves
        finally:
            db.close()


def test_blank_lines_are_skipped_and_zero_is_kept():
    db = SessionLocal()
    try:
        butter = db.query(Product).filter(Product.name == "Butter").one()
        eggs = db.query(Product).filter(Product.name == "Eggs").one()
        result = save_count(db, "walk-in", {butter.id: "", eggs.id: "0"}, "Partial")
        assert result["ok"] is True
        assert result["saved"] == 1
        sheet = count_sheet(db, "walk-in")
        names = [row["product"].name for row in sheet["rows"]]
        assert "Butter" in names
        assert default_location(butter) == "walk-in"
    finally:
        db.close()
