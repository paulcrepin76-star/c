from __future__ import annotations

from sqlalchemy import inspect, text

NEW_COLUMNS = {
    "suppliers": (
        ("delivery_fee", "NUMERIC(12, 2) DEFAULT 0"),
        ("min_order", "NUMERIC(12, 2) DEFAULT 0"),
        ("trip_cost", "NUMERIC(12, 2) DEFAULT 0"),
        ("city", "VARCHAR(80) DEFAULT ''"),
        ("miles", "NUMERIC(8, 1) DEFAULT 0"),
    ),
    "products": (
        ("compare_unit", "VARCHAR(20) DEFAULT ''"),
        ("purchasing_category", "VARCHAR(40) DEFAULT ''"),
    ),
    "purchase_prices": (
        ("url", "VARCHAR(400) DEFAULT ''"),
        ("miles", "NUMERIC(8, 1) DEFAULT 0"),
        ("location_label", "VARCHAR(160) DEFAULT ''"),
        ("is_discounted", "BOOLEAN DEFAULT FALSE"),
    ),
}


def ensure_schema(engine) -> None:
    """create_all will not add columns to tables that already exist on Unraid."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table, columns in NEW_COLUMNS.items():
        if table not in tables:
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl in columns:
            if name in existing:
                continue
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
