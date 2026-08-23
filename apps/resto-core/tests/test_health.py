from datetime import date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.health import data_health, mapping_coverage
from app.main import app
from app.models import Sale, SellableItem


def test_home_and_recipes_hide_fake_finished_numbers():
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Report " in home.text
        assert "never counted" in home.text
        assert "no punch clock" in home.text
        assert "QuickBooks" in home.text
        costing = client.get("/costing")
        assert costing.status_code == 200
        assert "Report " in costing.text
        match = client.get("/costing/match")
        assert match.status_code == 200
        assert "Match Square items" in match.text
        assert "Auto-match now" in match.text


def test_thin_square_sales_hide_operating_profit():
    db = SessionLocal()
    try:
        start = date.today().replace(day=1)
        health = data_health(
            db,
            start,
            date.today(),
            {"net_sales": Decimal("632.21"), "categorized_spend": Decimal("44565.24")},
        )
        assert health["show_profit"] is False
        assert health["confidence"] == "unreliable"
        assert "too small" in health["summary"]
    finally:
        db.close()


def test_mapping_coverage_counts_unmapped_sales():
    db = SessionLocal()
    try:
        item = SellableItem(name="Unmapped hashbrown", costing_group="food", selling_price=Decimal("8"))
        db.add(item)
        db.flush()
        db.add(Sale(sold_at=datetime.combine(date.today(), datetime.min.time()).replace(hour=10), sellable_item_id=item.id, qty=1, unit_price=Decimal("8"), revenue=Decimal("8"), square_order_id="h-cov", square_line_id="1"))
        db.commit()
        start = date.today()
        coverage = mapping_coverage(db, start, start)
        assert coverage["unmapped_sales"] >= Decimal("8")
        assert coverage["unmapped_pct"] >= 0
    finally:
        db.close()
