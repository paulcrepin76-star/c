from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

Money = Numeric(12, 2)
Qty = Numeric(14, 4)
UnitCost = Numeric(14, 6)


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    category: Mapped[str] = mapped_column(String(40), default="food")
    email_domain: Mapped[str] = mapped_column(String(120), default="")
    default_invoice_type: Mapped[str] = mapped_column(String(40), default="food")
    notes: Mapped[str] = mapped_column(Text, default="")
    delivery_fee: Mapped[Decimal] = mapped_column(Money, default=0)
    min_order: Mapped[Decimal] = mapped_column(Money, default=0)
    trip_cost: Mapped[Decimal] = mapped_column(Money, default=0)
    city: Mapped[str] = mapped_column(String(80), default="")
    miles: Mapped[Decimal] = mapped_column(Numeric(8, 1), default=0)

    invoices: Mapped[list[Invoice]] = relationship(back_populates="supplier")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40), default="food")
    base_unit: Mapped[str] = mapped_column(String(20), default="g")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    current_cost: Mapped[Decimal] = mapped_column(UnitCost, default=0)
    mealie_food_id: Mapped[str] = mapped_column(String(80), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    compare_unit: Mapped[str] = mapped_column(String(20), default="")
    purchasing_category: Mapped[str] = mapped_column(String(40), default="")

    wine: Mapped[WineProfile | None] = relationship(back_populates="product", uselist=False)
    sellables: Mapped[list[SellableItem]] = relationship(back_populates="product")


class WineProfile(Base):
    __tablename__ = "wine_profiles"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    producer: Mapped[str] = mapped_column(String(160), default="")
    vintage: Mapped[str] = mapped_column(String(16), default="")
    color: Mapped[str] = mapped_column(String(20), default="red")
    country: Mapped[str] = mapped_column(String(80), default="")
    region: Mapped[str] = mapped_column(String(120), default="")
    appellation: Mapped[str] = mapped_column(String(120), default="")
    grape: Mapped[str] = mapped_column(String(120), default="")
    bottle_size_ml: Mapped[int] = mapped_column(Integer, default=750)
    glass_pour_ml: Mapped[int] = mapped_column(Integer, default=150)
    bin_location: Mapped[str] = mapped_column(String(40), default="")
    par_bottles: Mapped[Decimal] = mapped_column(Qty, default=0)
    list_type: Mapped[str] = mapped_column(String(20), default="both")  # glass, bottle, both, cellar

    product: Mapped[Product] = relationship(back_populates="wine")


class SellableItem(Base):
    __tablename__ = "sellable_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    costing_group: Mapped[str] = mapped_column(String(40), default="food")
    serving_qty: Mapped[Decimal] = mapped_column(Qty, default=1)
    serving_unit: Mapped[str] = mapped_column(String(20), default="each")
    selling_price: Mapped[Decimal] = mapped_column(Money, default=0)
    square_item_id: Mapped[str] = mapped_column(String(80), default="")
    square_variation_id: Mapped[str] = mapped_column(String(80), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    product: Mapped[Product | None] = relationship(back_populates="sellables")
    recipe: Mapped[Recipe | None] = relationship(back_populates="sellables")
    sales: Mapped[list[Sale]] = relationship(back_populates="sellable")


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mealie_id: Mapped[str] = mapped_column(String(80), default="")
    name: Mapped[str] = mapped_column(String(200))
    yield_qty: Mapped[Decimal] = mapped_column(Qty, default=1)
    yield_unit: Mapped[str] = mapped_column(String(20), default="portion")
    notes: Mapped[str] = mapped_column(Text, default="")

    lines: Mapped[list[RecipeLine]] = relationship(back_populates="recipe", cascade="all, delete-orphan")
    sellables: Mapped[list[SellableItem]] = relationship(back_populates="recipe")


class RecipeLine(Base):
    __tablename__ = "recipe_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(Qty, default=0)
    unit: Mapped[str] = mapped_column(String(20), default="g")

    recipe: Mapped[Recipe] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    paperless_id: Mapped[str] = mapped_column(String(80), default="")
    number: Mapped[str] = mapped_column(String(80), default="")
    issued_on: Mapped[date | None] = mapped_column(Date)
    total: Mapped[Decimal] = mapped_column(Money, default=0)
    invoice_type: Mapped[str] = mapped_column(String(40), default="food")
    status: Mapped[str] = mapped_column(String(40), default="filed")
    title: Mapped[str] = mapped_column(String(240), default="")

    supplier: Mapped[Supplier | None] = relationship(back_populates="invoices")
    lines: Mapped[list[InvoiceLine]] = relationship(back_populates="invoice", cascade="all, delete-orphan")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    raw_description: Mapped[str] = mapped_column(String(240))
    qty: Mapped[Decimal] = mapped_column(Qty, default=0)
    unit: Mapped[str] = mapped_column(String(20), default="each")
    unit_cost: Mapped[Decimal] = mapped_column(Money, default=0)
    line_total: Mapped[Decimal] = mapped_column(Money, default=0)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))

    invoice: Mapped[Invoice] = relationship(back_populates="lines")
    product: Mapped[Product | None] = relationship()


class ProductAlias(Base):
    __tablename__ = "product_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    alias: Mapped[str] = mapped_column(String(160))
    exclude: Mapped[str] = mapped_column(String(240), default="")

    product: Mapped[Product] = relationship()

    __table_args__ = (UniqueConstraint("product_id", "alias", name="uq_product_alias"),)


class PurchasePrice(Base):
    __tablename__ = "purchase_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    invoice_line_id: Mapped[int | None] = mapped_column(ForeignKey("invoice_lines.id"), nullable=True)
    purchased_on: Mapped[date | None] = mapped_column(Date)
    sku: Mapped[str] = mapped_column(String(80), default="")
    raw_description: Mapped[str] = mapped_column(String(240), default="")
    pack_qty: Mapped[Decimal] = mapped_column(Qty, default=0)
    pack_unit: Mapped[str] = mapped_column(String(20), default="")
    pack_price: Mapped[Decimal] = mapped_column(Money, default=0)
    qty_base: Mapped[Decimal] = mapped_column(Qty, default=0)
    unit_cost_base: Mapped[Decimal] = mapped_column(UnitCost, default=0)
    compare_qty: Mapped[Decimal] = mapped_column(Qty, default=0)
    unit_cost_compare: Mapped[Decimal] = mapped_column(UnitCost, default=0)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=1)
    source: Mapped[str] = mapped_column(String(20), default="invoice")
    url: Mapped[str] = mapped_column(String(400), default="")
    miles: Mapped[Decimal] = mapped_column(Numeric(8, 1), default=0)
    location_label: Mapped[str] = mapped_column(String(160), default="")
    is_discounted: Mapped[bool] = mapped_column(Boolean, default=False)

    product: Mapped[Product] = relationship()
    supplier: Mapped[Supplier] = relationship()

    __table_args__ = (UniqueConstraint("invoice_line_id", name="uq_purchase_invoice_line"),)


class StockMove(Base):
    __tablename__ = "stock_moves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    qty_base: Mapped[Decimal] = mapped_column(Qty, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Money, default=0)
    reason: Mapped[str] = mapped_column(String(40), default="receive")
    location: Mapped[str] = mapped_column(String(40), default="cellar")
    notes: Mapped[str] = mapped_column(Text, default="")
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id"))

    product: Mapped[Product] = relationship()


class InventoryCount(Base):
    __tablename__ = "inventory_counts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    counted_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    location: Mapped[str] = mapped_column(String(40), default="cellar")
    notes: Mapped[str] = mapped_column(Text, default="")

    lines: Mapped[list[InventoryCountLine]] = relationship(back_populates="count", cascade="all, delete-orphan")


class InventoryCountLine(Base):
    __tablename__ = "inventory_count_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    count_id: Mapped[int] = mapped_column(ForeignKey("inventory_counts.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    counted_qty_base: Mapped[Decimal] = mapped_column(Qty, default=0)
    expected_qty_base: Mapped[Decimal] = mapped_column(Qty, default=0)

    count: Mapped[InventoryCount] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sold_at: Mapped[datetime] = mapped_column(DateTime)
    sellable_item_id: Mapped[int] = mapped_column(ForeignKey("sellable_items.id"))
    qty: Mapped[Decimal] = mapped_column(Qty, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Money, default=0)
    revenue: Mapped[Decimal] = mapped_column(Money, default=0)
    square_order_id: Mapped[str] = mapped_column(String(80), default="")
    square_line_id: Mapped[str] = mapped_column(String(80), default="")

    sellable: Mapped[SellableItem] = relationship(back_populates="sales")

    __table_args__ = (UniqueConstraint("square_order_id", "square_line_id", name="uq_square_line"),)


class Connector(Base):
    __tablename__ = "connectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="email")  # email, api, portal
    status: Mapped[str] = mapped_column(String(20), default="not_connected")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="not_connected")
    access_token: Mapped[str] = mapped_column(Text, default="")
    refresh_token: Mapped[str] = mapped_column(Text, default="")
    extra: Mapped[str] = mapped_column(Text, default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class ProductEquivalent(Base):
    """One supplier pack that maps to a restaurant ingredient (butter at Chef's vs Costco)."""

    __tablename__ = "product_equivalents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    sku: Mapped[str] = mapped_column(String(80), default="")
    upc: Mapped[str] = mapped_column(String(80), default="")
    brand: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(String(240), default="")
    pack_qty: Mapped[Decimal] = mapped_column(Qty, default=0)
    pack_unit: Mapped[str] = mapped_column(String(20), default="")
    case_qty: Mapped[Decimal] = mapped_column(Qty, default=0)
    last_price: Mapped[Decimal] = mapped_column(Money, default=0)
    last_seen: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(20), default="catalog")
    url: Mapped[str] = mapped_column(String(400), default="")

    product: Mapped[Product] = relationship()
    supplier: Mapped[Supplier] = relationship()

    __table_args__ = (UniqueConstraint("supplier_id", "sku", name="uq_equivalent_supplier_sku"),)


class CatalogItem(Base):
    """A listing captured on a given day. Unmatched discovery rows stay here."""

    __tablename__ = "catalog_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    sku: Mapped[str] = mapped_column(String(80), default="")
    upc: Mapped[str] = mapped_column(String(80), default="")
    brand: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(String(240), default="")
    pack_qty: Mapped[Decimal] = mapped_column(Qty, default=0)
    pack_unit: Mapped[str] = mapped_column(String(20), default="")
    case_qty: Mapped[Decimal] = mapped_column(Qty, default=0)
    regular_price: Mapped[Decimal] = mapped_column(Money, default=0)
    promo_price: Mapped[Decimal] = mapped_column(Money, default=0)
    location_label: Mapped[str] = mapped_column(String(160), default="")
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    captured_on: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(20), default="catalog")
    scan_mode: Mapped[str] = mapped_column(String(20), default="refresh")
    url: Mapped[str] = mapped_column(String(400), default="")

    product: Mapped[Product | None] = relationship()
    supplier: Mapped[Supplier] = relationship()

    __table_args__ = (UniqueConstraint("supplier_id", "sku", "captured_on", name="uq_catalog_item_day"),)
