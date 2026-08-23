from datetime import date, datetime, timedelta
from decimal import Decimal

from app.db import SessionLocal
from app.models import Sale, SellableItem
from app.sales_report import prior_window, sales_category, sales_report


def test_sales_category_puts_gift_cards_and_coffee_apart():
    assert sales_category("eGift Card") == "Gift cards"
    assert sales_category("Gift Card") == "Gift cards"
    assert sales_category("cafe latte") == "Coffee"
    assert sales_category("survey breakfast plate") == "Breakfast plates"
    assert sales_category("sancerre") == "Wine"
    assert sales_category("Mimosa") == "Cocktails"
    assert sales_category("house ipa") == "Beer"


def test_prior_window_is_the_same_dates_last_year():
    start, end = prior_window(date(2026, 1, 1), date(2026, 8, 23))
    assert start == date(2025, 1, 1)
    assert end == date(2025, 8, 23)


def test_sales_report_compares_this_year_to_last_year():
    db = SessionLocal()
    try:
        latte = SellableItem(name="cafe latte", costing_group="beverage", selling_price=Decimal("5.00"))
        card = SellableItem(name="Gift Card", costing_group="other", selling_price=Decimal("50.00"))
        db.add_all([latte, card])
        db.flush()
        this_year = datetime(date.today().year, 1, 15, 9, 0)
        last_year = this_year.replace(year=this_year.year - 1)
        db.add_all(
            [
                Sale(sold_at=this_year, sellable_item_id=latte.id, qty=2, unit_price=Decimal("5"), revenue=Decimal("10"), square_order_id="t1", square_line_id="a"),
                Sale(sold_at=this_year, sellable_item_id=card.id, qty=1, unit_price=Decimal("50"), revenue=Decimal("50"), square_order_id="t2", square_line_id="b"),
                Sale(sold_at=last_year, sellable_item_id=latte.id, qty=1, unit_price=Decimal("5"), revenue=Decimal("5"), square_order_id="l1", square_line_id="a"),
            ]
        )
        db.commit()
        start = date(date.today().year, 1, 1)
        end = date(date.today().year, 1, 31)
        report = sales_report(db, start, end)
        assert report["sales"]["now"] == Decimal("60.00")
        assert report["sales"]["then"] == Decimal("5.00")
        assert report["sales"]["delta"] == Decimal("55.00")
        assert report["gifts"]["now"] == Decimal("50.00")
        assert report["top_items"][0]["name"] == "Gift Card"
        assert any(row["name"] == "Gift cards" for row in report["categories"])
        assert report["has_last_year"] is True
    finally:
        db.close()
