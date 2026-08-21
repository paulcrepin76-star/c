from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Invoice, InvoiceLine, Product, Sale, SellableItem, StockMove, Supplier
from app.services import period_costing, wine_rows

router = APIRouter(prefix="/api")


def require_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if not x_api_key or x_api_key != settings.resto_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


class SaleIn(BaseModel):
    sold_at: datetime
    name: str
    qty: Decimal = 1
    unit_price: Decimal = 0
    revenue: Decimal | None = None
    square_order_id: str = ""
    square_line_id: str = ""
    square_item_id: str = ""
    costing_group: str = "food"


class SalesBatch(BaseModel):
    sales: list[SaleIn]


class PaperlessDocument(BaseModel):
    id: str | int
    title: str = ""
    correspondent: str | None = None
    created: str | None = None
    invoice_number: str = ""
    total: Decimal = Decimal(0)
    invoice_type: str = "food"
    lines: list[dict] = Field(default_factory=list)


@router.get("/health")
def api_health():
    return {"ok": True}


@router.get("/costing/summary", dependencies=[Depends(require_key)])
def costing_summary(days: int = 7, db: Session = Depends(get_db)):
    end = datetime.now(UTC).replace(tzinfo=None)
    start = end - timedelta(days=days)
    return period_costing(db, start, end)


@router.get("/wines", dependencies=[Depends(require_key)])
def wines_json(db: Session = Depends(get_db)):
    rows = []
    for row in wine_rows(db):
        rows.append(
            {
                "id": row["product"].id,
                "sku": row["product"].sku,
                "name": row["product"].name,
                "producer": row["profile"].producer,
                "vintage": row["profile"].vintage,
                "color": row["profile"].color,
                "bin": row["profile"].bin_location,
                "on_hand_bottles": float(row["on_hand_bottles"]),
                "par_bottles": float(row["profile"].par_bottles or 0),
                "bottle_cost": float(row["bottle_cost"]),
                "glass_cost": float(row["glass_cost"]),
                "glass_price": float(row["glass_price"]),
                "bottle_price": float(row["bottle_price"]),
                "glass_cost_pct": float(row["glass_cost_pct"]),
                "cellar_value": float(row["cellar_value"]),
            }
        )
    return {"wines": rows}


def _match_sellable(db: Session, incoming: SaleIn) -> SellableItem | None:
    if incoming.square_item_id:
        item = db.query(SellableItem).filter(SellableItem.square_item_id == incoming.square_item_id).first()
        if item:
            return item
    return db.query(SellableItem).filter(SellableItem.name.ilike(incoming.name)).first()


@router.post("/sales/import", dependencies=[Depends(require_key)])
def import_sales(batch: SalesBatch, db: Session = Depends(get_db)):
    created = 0
    skipped = 0
    for incoming in batch.sales:
        if incoming.square_order_id and incoming.square_line_id:
            exists = (
                db.query(Sale)
                .filter(Sale.square_order_id == incoming.square_order_id, Sale.square_line_id == incoming.square_line_id)
                .first()
            )
            if exists:
                skipped += 1
                continue
        item = _match_sellable(db, incoming)
        if item is None:
            item = SellableItem(
                name=incoming.name,
                costing_group=incoming.costing_group,
                selling_price=incoming.unit_price,
                square_item_id=incoming.square_item_id,
            )
            db.add(item)
            db.flush()
        revenue = incoming.revenue if incoming.revenue is not None else incoming.unit_price * incoming.qty
        sale = Sale(
            sold_at=incoming.sold_at,
            sellable_item_id=item.id,
            qty=incoming.qty,
            unit_price=incoming.unit_price,
            revenue=revenue,
            square_order_id=incoming.square_order_id,
            square_line_id=incoming.square_line_id or incoming.name,
        )
        db.add(sale)
        db.flush()
        if item.product_id and item.serving_unit == "ml":
            db.add(
                StockMove(
                    product_id=item.product_id,
                    occurred_at=incoming.sold_at,
                    qty_base=-(Decimal(item.serving_qty) * Decimal(incoming.qty)),
                    reason="sale",
                    location="bar",
                    sale_id=sale.id,
                )
            )
        created += 1
    db.commit()
    return {"created": created, "skipped": skipped}


@router.post("/webhooks/paperless", dependencies=[Depends(require_key)])
def paperless_webhook(doc: PaperlessDocument, db: Session = Depends(get_db)):
    existing = db.query(Invoice).filter(Invoice.paperless_id == str(doc.id)).first()
    if existing:
        return {"status": "duplicate", "invoice_id": existing.id}

    supplier = None
    if doc.correspondent:
        supplier = db.query(Supplier).filter(Supplier.name.ilike(doc.correspondent)).first()
        if supplier is None:
            supplier = Supplier(name=doc.correspondent, category=doc.invoice_type, default_invoice_type=doc.invoice_type)
            db.add(supplier)
            db.flush()

    issued_on = None
    if doc.created:
        try:
            issued_on = datetime.fromisoformat(doc.created.replace("Z", "")).date()
        except ValueError:
            issued_on = None

    invoice = Invoice(
        supplier_id=supplier.id if supplier else None,
        paperless_id=str(doc.id),
        number=doc.invoice_number,
        issued_on=issued_on,
        total=doc.total,
        invoice_type=doc.invoice_type,
        status="filed",
        title=doc.title,
    )
    db.add(invoice)
    db.flush()
    for line in doc.lines:
        description = str(line.get("description") or line.get("raw_description") or "")
        product = None
        if description:
            product = db.query(Product).filter(Product.name.ilike(f"%{description}%")).first()
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


@router.post("/jobs/nightly", dependencies=[Depends(require_key)])
def nightly(db: Session = Depends(get_db)):
    end = datetime.now(UTC).replace(tzinfo=None)
    start = end - timedelta(days=1)
    costing = period_costing(db, start, end)
    low_stock = [row["product"].name for row in wine_rows(db) if row["below_par"]]
    return {
        "ran_at": end.isoformat(),
        "yesterday": costing["groups"],
        "wine_below_par": low_stock,
        "hint": "n8n should pull Square/Mealie into /api/sales/import before this job, and drop new PDFs in the Paperless consume folder.",
    }
