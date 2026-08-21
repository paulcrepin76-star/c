from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    Connection,
    Connector,
    Invoice,
    InvoiceLine,
    Product,
    Recipe,
    RecipeLine,
    Sale,
    SellableItem,
    StockMove,
    Supplier,
    WineProfile,
)
from app.vendors import vendor_names

CONNECTION_NAMES = ("square", "mealie", "paperless")


def _fold_alias_suppliers(db: Session, vendor: dict, canonical: Supplier) -> None:
    exact = {name.lower() for name in vendor_names(vendor)}
    needles = [str(item).lower() for item in (vendor.get("match_needles") or [])]
    others = db.query(Supplier).filter(Supplier.id != canonical.id).all()
    for other in others:
        lowered = other.name.lower()
        if lowered not in exact and not any(needle and needle in lowered for needle in needles):
            continue
        db.query(Invoice).filter(Invoice.supplier_id == other.id).update({"supplier_id": canonical.id})
        db.delete(other)


def ensure_vendors(db: Session) -> None:
    from app.connections import get_connection
    from app.vendors import VENDORS

    for vendor in VENDORS:
        names = vendor_names(vendor)
        supplier = db.query(Supplier).filter(Supplier.name.in_(names)).first()
        if supplier is None:
            supplier = Supplier(
                name=vendor["label"],
                category=vendor["kind"],
                email_domain=vendor["email_domain"],
                default_invoice_type=vendor["invoice_type"],
            )
            db.add(supplier)
            db.flush()
        else:
            supplier.name = vendor["label"]
            supplier.category = vendor["kind"]
            supplier.default_invoice_type = vendor["invoice_type"]
            if vendor["email_domain"]:
                supplier.email_domain = vendor["email_domain"]
        _fold_alias_suppliers(db, vendor, supplier)

        connector = db.query(Connector).filter(Connector.name.in_(names)).first()
        if connector is None:
            db.add(
                Connector(
                    name=vendor["label"],
                    kind="email",
                    status="not_connected",
                    notes=vendor["blurb"],
                )
            )
        else:
            connector.name = vendor["label"]
            connector.notes = vendor["blurb"] or connector.notes

        canonical = db.query(Connection).filter(Connection.name == vendor["slug"]).first()
        if canonical is None:
            legacy = db.query(Connection).filter(Connection.name.in_(vendor.get("legacy_slugs") or [])).first()
            if legacy:
                legacy.name = vendor["slug"]
                canonical = legacy
            else:
                canonical = get_connection(db, vendor["slug"])
        if vendor["slug"] == "fpl" and canonical is not None:
            from app.connections import extra_dict, set_extra

            extra = extra_dict(canonical)
            if not extra.get("business_statements"):
                login = str(extra.get("login") or "")
                set_extra(
                    canonical,
                    business_statements=vendor.get("business_statements") or 24,
                    personal_unattached=True,
                    e_bill_email=extra.get("e_bill_email") or (login if "@" in login else vendor.get("e_bill_email") or ""),
                )
    db.commit()


def ensure_connections(db: Session) -> None:
    existing = {row.name for row in db.query(Connection).all()}
    for name in CONNECTION_NAMES:
        if name not in existing:
            db.add(Connection(name=name, status="not_connected"))
    db.commit()
    ensure_vendors(db)


def seed_if_empty(db: Session) -> None:
    if db.query(Product).count() > 0:
        return

    sams = Supplier(name="Sam's Club", category="food", email_domain="samsclub.com", default_invoice_type="food")
    chefs = Supplier(name="Chef's Warehouse", category="food", email_domain="chefswarehouse.com", default_invoice_type="food")
    costco = Supplier(name="Costco", category="food", email_domain="costco.com", default_invoice_type="food")
    gordon = Supplier(name="Gordon Food Service", category="food", email_domain="gfs.com", default_invoice_type="food")
    wine_co = Supplier(name="Wine distributor", category="wine", default_invoice_type="wine")
    fpl = Supplier(name="FPL Bonita Springs", category="utility", email_domain="fpl.com", default_invoice_type="utility")
    db.add_all([sams, chefs, costco, gordon, wine_co, fpl])
    db.flush()

    eggs = Product(sku="EGG", name="Eggs", category="dairy", base_unit="each", current_cost=Decimal("0.266"), compare_unit="each", purchasing_category="dairy")
    milk = Product(sku="MILK", name="Milk", category="dairy", base_unit="ml", current_cost=Decimal("0.0018"), compare_unit="gal", purchasing_category="dairy")
    butter = Product(sku="BUTTER", name="Butter", category="dairy", base_unit="g", current_cost=Decimal("0.0120"), compare_unit="lb", purchasing_category="dairy")
    orange = Product(sku="OJ", name="Orange juice", category="beverage", base_unit="ml", current_cost=Decimal("0.0040"))
    brandy = Product(sku="BRANDY", name="Brandy", category="spirit", base_unit="ml", current_cost=Decimal("0.0293"))
    db.add_all([eggs, milk, butter, orange, brandy])
    db.flush()

    wines = [
        {
            "sku": "SB-LOIRE-24",
            "name": "Sauvignon Blanc",
            "producer": "Domaine Loire",
            "vintage": "2024",
            "color": "white",
            "country": "France",
            "region": "Loire",
            "appellation": "Sancerre",
            "grape": "Sauvignon Blanc",
            "bin": "W12",
            "par": 12,
            "cost": Decimal("15.00"),
            "glass": Decimal("11.00"),
            "bottle": Decimal("42.00"),
            "list_type": "both",
            "on_hand_bottles": 10,
        },
        {
            "sku": "PN-BURG-22",
            "name": "Pinot Noir",
            "producer": "Maison Burgundy",
            "vintage": "2022",
            "color": "red",
            "country": "France",
            "region": "Burgundy",
            "appellation": "Bourgogne",
            "grape": "Pinot Noir",
            "bin": "R04",
            "par": 8,
            "cost": Decimal("18.50"),
            "glass": Decimal("14.00"),
            "bottle": Decimal("56.00"),
            "list_type": "both",
            "on_hand_bottles": 6,
        },
        {
            "sku": "CHAMP-NV",
            "name": "Champagne Brut NV",
            "producer": "House Sparkling",
            "vintage": "NV",
            "color": "sparkling",
            "country": "France",
            "region": "Champagne",
            "appellation": "Champagne",
            "grape": "Chardonnay / Pinot Noir",
            "bin": "S01",
            "par": 6,
            "cost": Decimal("28.00"),
            "glass": Decimal("18.00"),
            "bottle": Decimal("85.00"),
            "list_type": "both",
            "on_hand_bottles": 4,
        },
        {
            "sku": "HOUSE-RED",
            "name": "House red",
            "producer": "House pour",
            "vintage": "2023",
            "color": "red",
            "country": "Spain",
            "region": "Rioja",
            "appellation": "Rioja",
            "grape": "Tempranillo",
            "bin": "BAR",
            "par": 18,
            "cost": Decimal("8.40"),
            "glass": Decimal("9.00"),
            "bottle": Decimal("28.00"),
            "list_type": "both",
            "on_hand_bottles": 16,
        },
    ]

    wine_products: dict[str, Product] = {}
    sellables: dict[str, SellableItem] = {}
    now = datetime.now(UTC).replace(tzinfo=None)

    for item in wines:
        product = Product(
            sku=item["sku"],
            name=item["name"],
            category="wine",
            base_unit="ml",
            current_cost=item["cost"] / Decimal("750"),
            notes=item["producer"],
        )
        db.add(product)
        db.flush()
        db.add(
            WineProfile(
                product_id=product.id,
                producer=item["producer"],
                vintage=item["vintage"],
                color=item["color"],
                country=item["country"],
                region=item["region"],
                appellation=item["appellation"],
                grape=item["grape"],
                bottle_size_ml=750,
                glass_pour_ml=150,
                bin_location=item["bin"],
                par_bottles=item["par"],
                list_type=item["list_type"],
            )
        )
        glass = SellableItem(
            product_id=product.id,
            name=f"{item['name']} glass",
            costing_group="wine",
            serving_qty=150,
            serving_unit="ml",
            selling_price=item["glass"],
        )
        bottle = SellableItem(
            product_id=product.id,
            name=f"{item['name']} bottle",
            costing_group="wine",
            serving_qty=750,
            serving_unit="ml",
            selling_price=item["bottle"],
        )
        db.add_all([glass, bottle])
        db.flush()
        db.add(
            StockMove(
                product_id=product.id,
                occurred_at=now - timedelta(days=12),
                qty_base=Decimal(item["on_hand_bottles"]) * Decimal("750"),
                unit_cost=item["cost"],
                reason="receive",
                location="cellar",
                notes="Opening cellar",
            )
        )
        wine_products[item["sku"]] = product
        sellables[f"{item['sku']}-glass"] = glass
        sellables[f"{item['sku']}-bottle"] = bottle

    sangria = Recipe(name="Sangria", mealie_id="", yield_qty=1, yield_unit="glass", notes="Demo cocktail recipe")
    croissant = Recipe(name="Croissant", mealie_id="", yield_qty=1, yield_unit="each", notes="Demo pastry")
    toast = Recipe(name="French Toast", mealie_id="", yield_qty=1, yield_unit="each")
    hollandaise = Recipe(name="Hollandaise", mealie_id="", yield_qty=1, yield_unit="each")
    db.add_all([sangria, croissant, toast, hollandaise])
    db.flush()
    db.add_all(
        [
            RecipeLine(recipe_id=sangria.id, product_id=wine_products["HOUSE-RED"].id, qty=120, unit="ml"),
            RecipeLine(recipe_id=sangria.id, product_id=brandy.id, qty=15, unit="ml"),
            RecipeLine(recipe_id=sangria.id, product_id=orange.id, qty=30, unit="ml"),
            RecipeLine(recipe_id=croissant.id, product_id=butter.id, qty=50, unit="g"),
            RecipeLine(recipe_id=toast.id, product_id=butter.id, qty=35, unit="g"),
            RecipeLine(recipe_id=toast.id, product_id=eggs.id, qty=1, unit="each"),
            RecipeLine(recipe_id=hollandaise.id, product_id=butter.id, qty=60, unit="g"),
            RecipeLine(recipe_id=hollandaise.id, product_id=eggs.id, qty=2, unit="each"),
        ]
    )
    sangria_item = SellableItem(
        recipe_id=sangria.id,
        name="Sangria",
        costing_group="beverage",
        serving_qty=1,
        serving_unit="glass",
        selling_price=Decimal("12.00"),
    )
    db.add(sangria_item)
    db.flush()

    invoice = Invoice(
        supplier_id=wine_co.id,
        number="W-1042",
        issued_on=(now - timedelta(days=12)).date(),
        total=Decimal("327.60"),
        invoice_type="wine",
        status="received",
        title="Wine delivery 08/09",
    )
    db.add(invoice)
    db.flush()
    db.add(
        InvoiceLine(
            invoice_id=invoice.id,
            raw_description="Sauvignon Blanc 2024 x12",
            qty=12,
            unit="bottle",
            unit_cost=Decimal("15.00"),
            line_total=Decimal("180.00"),
            product_id=wine_products["SB-LOIRE-24"].id,
        )
    )

    food_invoice = Invoice(
        supplier_id=sams.id,
        number="SC-8891",
        issued_on=(now - timedelta(days=3)).date(),
        total=Decimal("327.84"),
        invoice_type="food",
        status="filed",
        title="Sam's Club 08/18",
    )
    db.add(food_invoice)
    db.flush()
    db.add_all(
        [
            InvoiceLine(invoice_id=food_invoice.id, raw_description="Eggs 15 dozen", qty=15, unit="dozen", unit_cost=Decimal("3.19"), line_total=Decimal("47.88"), product_id=eggs.id),
            InvoiceLine(invoice_id=food_invoice.id, raw_description="Milk 2 gal", qty=2, unit="gal", unit_cost=Decimal("3.99"), line_total=Decimal("7.98"), product_id=milk.id),
            InvoiceLine(invoice_id=food_invoice.id, raw_description="Butter 4 lb pack", qty=1, unit="pack", unit_cost=Decimal("21.20"), line_total=Decimal("21.20"), product_id=butter.id),
        ]
    )

    chefs_invoice = Invoice(
        supplier_id=chefs.id,
        number="CW-48382",
        issued_on=(now - timedelta(days=5)).date(),
        total=Decimal("201.60"),
        invoice_type="food",
        status="filed",
        title="Chef's Warehouse butter 36 lb",
    )
    gordon_invoice = Invoice(
        supplier_id=gordon.id,
        number="GFS-82736",
        issued_on=(now - timedelta(days=8)).date(),
        total=Decimal("159.00"),
        invoice_type="food",
        status="filed",
        title="Gordon 30 lb butter",
    )
    costco_invoice = Invoice(
        supplier_id=costco.id,
        number="C-921",
        issued_on=(now - timedelta(days=2)).date(),
        total=Decimal("25.68"),
        invoice_type="food",
        status="filed",
        title="Costco butter and eggs",
    )
    db.add_all([chefs_invoice, gordon_invoice, costco_invoice])
    db.flush()
    db.add_all(
        [
            InvoiceLine(invoice_id=chefs_invoice.id, raw_description="Butter unsalted 36 lb case SKU 48382", qty=1, unit="case", unit_cost=Decimal("201.60"), line_total=Decimal("201.60"), product_id=butter.id),
            InvoiceLine(invoice_id=gordon_invoice.id, raw_description="Butter 30 lb case SKU 82736", qty=1, unit="case", unit_cost=Decimal("159.00"), line_total=Decimal("159.00"), product_id=butter.id),
            InvoiceLine(invoice_id=costco_invoice.id, raw_description="Butter 4 lb pack SKU 921", qty=1, unit="pack", unit_cost=Decimal("19.96"), line_total=Decimal("19.96"), product_id=butter.id),
            InvoiceLine(invoice_id=costco_invoice.id, raw_description="Eggs 24 ct", qty=24, unit="each", unit_cost=Decimal("0.24"), line_total=Decimal("5.72"), product_id=eggs.id),
        ]
    )

    # Demo week of wine sales so dashboards are not empty.
    for day in range(7):
        sold_at = now - timedelta(days=day)
        db.add_all(
            [
                Sale(sold_at=sold_at, sellable_item_id=sellables["SB-LOIRE-24-glass"].id, qty=6, unit_price=Decimal("11.00"), revenue=Decimal("66.00"), square_order_id=f"demo-{day}", square_line_id="sb-g"),
                Sale(sold_at=sold_at, sellable_item_id=sellables["HOUSE-RED-glass"].id, qty=8, unit_price=Decimal("9.00"), revenue=Decimal("72.00"), square_order_id=f"demo-{day}", square_line_id="hr-g"),
                Sale(sold_at=sold_at, sellable_item_id=sellables["PN-BURG-22-glass"].id, qty=3, unit_price=Decimal("14.00"), revenue=Decimal("42.00"), square_order_id=f"demo-{day}", square_line_id="pn-g"),
                Sale(sold_at=sold_at, sellable_item_id=sangria_item.id, qty=2, unit_price=Decimal("12.00"), revenue=Decimal("24.00"), square_order_id=f"demo-{day}", square_line_id="sangria"),
            ]
        )
        db.add(
            StockMove(
                product_id=wine_products["SB-LOIRE-24"].id,
                occurred_at=sold_at,
                qty_base=Decimal("-900"),
                unit_cost=Decimal("15.00"),
                reason="sale",
                location="bar",
                notes="Demo glasses",
            )
        )
        db.add(
            StockMove(
                product_id=wine_products["HOUSE-RED"].id,
                occurred_at=sold_at,
                qty_base=Decimal("-1440"),
                unit_cost=Decimal("8.40"),
                reason="sale",
                location="bar",
                notes="Demo glasses + sangria wine",
            )
        )
        db.add(
            StockMove(
                product_id=wine_products["PN-BURG-22"].id,
                occurred_at=sold_at,
                qty_base=Decimal("-450"),
                unit_cost=Decimal("18.50"),
                reason="sale",
                location="bar",
            )
        )

    db.add_all(
        [
            Connector(name="Paperless email", kind="email", status="ready", notes="Best default: any supplier PDF that arrives by email."),
            Connector(name="Square", kind="api", status="not_connected", notes="Official API for sales. Click Connect on this site and log in yourself."),
            Connector(name="Mealie", kind="api", status="not_connected", notes="Recipes stay in Mealie. Click Connect and use your Mealie login."),
            Connector(name="Comcast", kind="email", status="not_connected", notes="Utility: Paperless is enough."),
            Connector(name="Waste Management", kind="email", status="not_connected", notes="Utility: Paperless is enough."),
            Connector(name="Wine distributor", kind="email", status="not_connected", notes="Receive bottles into the cellar from invoice lines."),
        ]
    )
    db.commit()
