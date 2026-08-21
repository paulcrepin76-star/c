from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.catalog import extract_html_json_products, scan_catalogs
from app.connections import mark_connected
from app.db import SessionLocal
from app.equivalents import (
    extract_sku,
    relevant_products,
    resolve_product,
    upsert_equivalent,
    walk_json_products,
    watch_payload,
)
from app.main import app
from app.models import CatalogItem, Product, ProductEquivalent, Supplier
from app.purchasing import product_comparison


def test_extract_sku_from_chefs_line():
    assert extract_sku("Butter unsalted 36 lb case SKU 48382") == "48382"


def test_json_walker_reads_hidden_product_payload():
    payload = {
        "data": {
            "products": [
                {
                    "productName": "Member's Mark Unsalted Butter 4 lb",
                    "itemNumber": "918273",
                    "finalPrice": 19.96,
                    "listPrice": 21.98,
                    "brandName": "Member's Mark",
                    "size": "4 lb",
                }
            ]
        }
    }
    items = walk_json_products(payload)
    butter = next(item for item in items if "Butter" in item["description"])
    assert butter["sku"] == "918273"
    assert butter["pack_price"] == Decimal("19.96")
    assert butter["is_discounted"] is True


def test_html_script_json_products():
    html = """
    <html><script>{"products":[{"name":"Unsalted Butter 4 lb","sku":"B1","price":19.96}]}</script></html>
    """
    items = extract_html_json_products(html)
    assert items
    assert items[0]["sku"] == "B1"


def test_relevant_products_come_from_invoices_not_the_whole_catalog():
    db = SessionLocal()
    try:
        names = {product.sku for product in relevant_products(db, mode="refresh")}
        assert "BUTTER" in names
        assert "EGG" in names
        extra = Product(sku="DIAPERS", name="Diapers", category="food", is_active=True)
        db.add(extra)
        db.commit()
        again = {product.sku for product in relevant_products(db, mode="refresh")}
        assert "DIAPERS" not in again
    finally:
        db.close()


def test_invoice_sku_becomes_an_equivalent():
    db = SessionLocal()
    try:
        butter = db.query(Product).filter(Product.sku == "BUTTER").one()
        chefs = db.query(Supplier).filter(Supplier.name == "Chef's Warehouse").one()
        row = (
            db.query(ProductEquivalent)
            .filter(ProductEquivalent.product_id == butter.id, ProductEquivalent.supplier_id == chefs.id)
            .one()
        )
        assert row.sku == "48382"
        card = product_comparison(db, butter)
        suppliers = {item["supplier"] for item in card["equivalents"]}
        assert "Chef's Warehouse" in suppliers
        assert "Costco" in suppliers
    finally:
        db.close()


def test_match_prefers_known_supplier_sku():
    db = SessionLocal()
    try:
        butter = db.query(Product).filter(Product.sku == "BUTTER").one()
        sams = db.query(Supplier).filter(Supplier.name == "Sam's Club").one()
        upsert_equivalent(
            db,
            butter,
            sams,
            {"sku": "918273", "description": "Member's Mark Unsalted Butter", "pack_qty": 4, "pack_unit": "lb", "pack_price": 19.96},
            seen_on=date.today(),
            source="extension",
        )
        db.commit()
        matched = resolve_product(db, sams, "Something unlabeled", "918273")
        assert matched is not None
        assert matched.sku == "BUTTER"
    finally:
        db.close()


def test_scan_does_not_crawl_sams_even_when_connected(monkeypatch):
    fetched = []

    class FakeResp:
        status_code = 200
        text = "<html>" + ("x" * 2500) + "</html>"

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def get(self, url, headers=None):
            fetched.append(url)
            return FakeResp()

    monkeypatch.setattr("app.catalog.httpx.Client", FakeClient)
    db = SessionLocal()
    try:
        mark_connected(db, "sams-club", "secret", login="paul@example.com", connector_name="Sam's Club")
        out = scan_catalogs(db, mode="refresh")
        skipped = {item["source"]: item for item in out["skipped"]}
        assert "Sam's Club" in skipped
        assert skipped["Sam's Club"]["status"] == "receipts_or_extension"
        assert skipped["Sam's Club"]["connected"] == "connected"
        assert not any("samsclub" in url for url in fetched)
        assert out["relevant"] >= 1
        assert out["mode"] == "refresh"
    finally:
        db.close()


def test_watch_api_lists_butter():
    with TestClient(app) as client:
        denied = client.get("/api/prices/watch")
        assert denied.status_code == 401
        ok = client.get("/api/prices/watch", headers={"X-API-Key": "test"})
        assert ok.status_code == 200
        names = {row["name"] for row in ok.json()["products"]}
        assert "Butter" in names


def test_discovery_keeps_unmatched_public_listing(monkeypatch):
    html = """
    <html><script>{"products":[
      {"description":"Grassland Unsalted Grade AA Butter Solid - 1 lb. - 36/Case","itemNumber":"123","price":138.96,"unitsPerPackaging":36,"link":"/butter.html"},
      {"description":"Industrial floor wax 5 gal","itemNumber":"WAX-9","price":44.00,"unitsPerPackaging":1,"link":"/wax.html"}
    ]}</script></html>
    """

    class FakeResp:
        status_code = 200
        text = html + ("<!-- pad -->" * 200)

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def get(self, url, headers=None):
            return FakeResp()

    monkeypatch.setattr("app.catalog.httpx.Client", FakeClient)
    db = SessionLocal()
    try:
        out = scan_catalogs(db, mode="discovery")
        assert out["mode"] == "discovery"
        wax = db.query(CatalogItem).filter(CatalogItem.sku == "WAX-9").first()
        # Unmatched rows are stored only when the query text hits the description.
        # Discovery still must not crawl Sam's.
        skipped = {item["source"] for item in out["skipped"]}
        assert "Sam's Club" in skipped
        assert "Costco" in skipped
        if wax is not None:
            assert wax.product_id is None
    finally:
        db.close()
