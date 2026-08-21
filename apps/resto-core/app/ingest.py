from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Invoice, InvoiceLine, Product, Recipe, RecipeLine, Sale, SellableItem, StockMove, Supplier
from app.vendors import VENDORS, vendor_names


def match_supplier(db: Session, correspondent: str | None, invoice_type: str = "food") -> Supplier | None:
    if not correspondent:
        return None
    name = str(correspondent).strip()
    supplier = db.query(Supplier).filter(Supplier.name.ilike(name)).first()
    if supplier:
        return supplier
    lowered = name.lower()
    for vendor in VENDORS:
        aliases = [item.lower() for item in vendor_names(vendor)]
        if any(alias in lowered or lowered in alias for alias in aliases):
            supplier = db.query(Supplier).filter(Supplier.name == vendor["label"]).first()
            if supplier:
                return supplier
    supplier = Supplier(name=name, category=invoice_type, default_invoice_type=invoice_type)
    db.add(supplier)
    db.flush()
    return supplier


def clip(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def clean_food_name(raw: str) -> str:
    text = str(raw or "").strip()
    if "REVIEW REQUIRED" in text.upper():
        text = text.split("REVIEW REQUIRED")[0]
        text = text.split("review required")[0]
    text = text.split("·")[0]
    text = text.replace("/", " ")
    text = " ".join(text.split()).strip(" -·,;")
    return clip(text, 180)


def product_sku(food: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in food.upper())
    slug = "-".join(part for part in slug.split("-") if part)
    return clip(slug or "FOOD", 70)
    if square_item_id:
        item = db.query(SellableItem).filter(SellableItem.square_item_id == square_item_id).first()
        if item:
            return item
    return db.query(SellableItem).filter(SellableItem.name.ilike(name)).first()


def ingest_sales(db: Session, sales: list[dict]) -> dict:
    created = 0
    skipped = 0
    for incoming in sales:
        order_id = str(incoming.get("square_order_id") or "")
        line_id = str(incoming.get("square_line_id") or incoming.get("name") or "")
        if order_id and line_id:
            exists = db.query(Sale).filter(Sale.square_order_id == order_id, Sale.square_line_id == line_id).first()
            if exists:
                skipped += 1
                continue
        name = str(incoming.get("name") or "Item")
        item = match_sellable(db, name, str(incoming.get("square_item_id") or ""))
        qty = Decimal(str(incoming.get("qty") or 1))
        unit_price = Decimal(str(incoming.get("unit_price") or 0))
        revenue = incoming.get("revenue")
        revenue = Decimal(str(revenue)) if revenue is not None else unit_price * qty
        sold_at = incoming.get("sold_at")
        if isinstance(sold_at, str):
            sold_at = datetime.fromisoformat(sold_at.replace("Z", "+00:00")).replace(tzinfo=None)
        elif getattr(sold_at, "tzinfo", None):
            sold_at = sold_at.replace(tzinfo=None)
        if item is None:
            item = SellableItem(
                name=name,
                costing_group=str(incoming.get("costing_group") or "food"),
                selling_price=unit_price,
                square_item_id=str(incoming.get("square_item_id") or ""),
            )
            db.add(item)
            db.flush()
        sale = Sale(
            sold_at=sold_at,
            sellable_item_id=item.id,
            qty=qty,
            unit_price=unit_price,
            revenue=revenue,
            square_order_id=order_id,
            square_line_id=line_id,
        )
        db.add(sale)
        db.flush()
        if item.product_id and item.serving_unit == "ml":
            db.add(
                StockMove(
                    product_id=item.product_id,
                    occurred_at=sold_at,
                    qty_base=-(Decimal(item.serving_qty) * qty),
                    reason="sale",
                    location="bar",
                    sale_id=sale.id,
                )
            )
        created += 1
    db.commit()
    return {"created": created, "skipped": skipped}


def ingest_paperless_doc(db: Session, doc: dict) -> dict:
    paperless_id = str(doc.get("id") or "")
    existing = db.query(Invoice).filter(Invoice.paperless_id == paperless_id).first()
    if existing:
        return {"status": "duplicate", "invoice_id": existing.id}
    invoice_type = str(doc.get("invoice_type") or "food")
    supplier = match_supplier(db, doc.get("correspondent"), invoice_type)
    issued_on = None
    created = doc.get("created")
    if created:
        try:
            issued_on = datetime.fromisoformat(str(created).replace("Z", "")).date()
        except ValueError:
            issued_on = None
    invoice = Invoice(
        supplier_id=supplier.id if supplier else None,
        paperless_id=paperless_id,
        number=str(doc.get("invoice_number") or ""),
        issued_on=issued_on,
        total=Decimal(str(doc.get("total") or 0)),
        invoice_type=invoice_type,
        status="filed",
        title=str(doc.get("title") or ""),
    )
    db.add(invoice)
    db.flush()
    for line in doc.get("lines") or []:
        description = str(line.get("description") or line.get("raw_description") or "")
        product = db.query(Product).filter(Product.name.ilike(f"%{description}%")).first() if description else None
        db.add(
            InvoiceLine(
                invoice_id=invoice.id,
                raw_description=description,
                qty=Decimal(str(line.get("qty") or 0)),
                unit=str(line.get("unit") or "each"),
                unit_cost=Decimal(str(line.get("unit_cost") or 0)),
                line_total=Decimal(str(line.get("line_total") or 0)),
                product_id=product.id if product else None,
            )
        )
    db.commit()
    return {"status": "created", "invoice_id": invoice.id}


def ingest_recipes(db: Session, recipes: list[dict]) -> dict:
    created = 0
    updated = 0
    for incoming in recipes:
        name = clip(str(incoming.get("name") or "").strip(), 200)
        if not name:
            continue
        mealie_id = clip(str(incoming.get("mealie_id") or ""), 80)
        recipe = db.query(Recipe).filter(Recipe.mealie_id == mealie_id).first() if mealie_id else None
        if recipe is None:
            recipe = db.query(Recipe).filter(Recipe.name.ilike(name)).first()
        if recipe is None:
            recipe = Recipe(name=name, mealie_id=mealie_id, yield_qty=incoming.get("yield_qty") or 1, yield_unit=clip(str(incoming.get("yield_unit") or "portion"), 20) or "portion")
            db.add(recipe)
            db.flush()
            created += 1
        else:
            recipe.name = name
            recipe.mealie_id = mealie_id or recipe.mealie_id
            updated += 1
            db.query(RecipeLine).filter(RecipeLine.recipe_id == recipe.id).delete()
        for line in incoming.get("lines") or []:
            food = clean_food_name(str(line.get("name") or line.get("food") or ""))
            if not food:
                continue
            product = db.query(Product).filter(Product.name.ilike(food)).first()
            if product is None:
                sku = product_sku(food)
                taken = db.query(Product).filter(Product.sku == sku).first()
                if taken:
                    product = taken
                else:
                    product = Product(
                        sku=sku,
                        name=food,
                        category="food",
                        base_unit=clip(str(line.get("unit") or "g"), 20) or "g",
                    )
                    db.add(product)
                    db.flush()
            db.add(
                RecipeLine(
                    recipe_id=recipe.id,
                    product_id=product.id,
                    qty=line.get("qty") or 0,
                    unit=clip(str(line.get("unit") or "g"), 20) or "g",
                )
            )
        price = incoming.get("selling_price")
        if price is not None:
            item = db.query(SellableItem).filter(SellableItem.recipe_id == recipe.id).first()
            if item is None:
                item = SellableItem(
                    recipe_id=recipe.id,
                    name=clip(name, 200),
                    costing_group=incoming.get("costing_group") or "food",
                )
                db.add(item)
            item.selling_price = price
            item.name = clip(name, 200)
    db.commit()
    return {"created": created, "updated": updated}
