from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.seed import seed_if_empty
from app.services import period_costing, wine_rows


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    seed_if_empty(db)
    return db


def test_seeded_cellar_has_sauvignon_math():
    db = _session()
    rows = wine_rows(db)
    assert len(rows) == 4
    sb = next(row for row in rows if row["product"].sku == "SB-LOIRE-24")
    assert sb["glass_cost"] == Decimal("3.00")
    assert sb["glass_cost_pct"] == Decimal("27.27")
    assert sb["on_hand_bottles"] < Decimal("10")


def test_period_costing_tracks_wine_and_sangria():
    db = _session()
    end = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
    start = end - timedelta(days=8)
    summary = period_costing(db, start, end)
    assert summary["groups"]["wine"]["sales"] > 0
    assert summary["groups"]["beverage"]["sales"] > 0
    assert any("Sauvignon" in row["name"] for row in summary["wines"])
