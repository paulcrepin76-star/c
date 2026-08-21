import os

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/resto-pytest.db")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("RESTO_API_KEY", "test")
os.environ.setdefault("RESTO_PUBLIC_URL", "http://100.116.48.120:8088")
os.environ["CATALOG_SCAN_ENABLED"] = "false"
os.environ["OPEN_PRICES_ENABLED"] = "false"
os.environ["BLS_ENABLED"] = "false"

import pytest


@pytest.fixture(autouse=True)
def reset_db():
    from app.db import Base, SessionLocal, engine
    from app.purchasing import backfill_purchase_prices, ensure_purchasing
    from app.seed import ensure_connections, seed_if_empty

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
        ensure_connections(db)
        ensure_purchasing(db)
        backfill_purchase_prices(db)
    finally:
        db.close()
    yield
