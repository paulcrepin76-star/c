"""Wine labels from purchase tickets — names only, no quantities."""

from __future__ import annotations

import re
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.connections import access_token_for
from app.models import Invoice, Product, WineProfile

PACK = re.compile(
    r"\b\d{1,2}\s*[xX/]\s*\d{2,4}\b|\b\d{1,2}/750\b|\b\d+\s*(?:btl|btl\.|bottles?)\b",
    re.I,
)
SKU = re.compile(r"\b[A-Z]{2,8}(?:-[A-Z0-9.+]{1,})+\b|\b[A-Z]{2,8}[A-Z0-9._-]*\d[A-Z0-9._-]*\+?\b", re.I)
PRICE = re.compile(r"\$?\d{1,4}(?:[.,]\d{2})")
YEAR = re.compile(r"\b(20\d{2})\b")
SKIP = re.compile(
    r"\b("
    r"invoice|subtotal|total|received|fintech|zelle|license|survey cafe|"
    r"belle gourmandise|davie|bonita|wilson|pierre delivery|sales tax|"
    r"payment|page|home|description|print name|breakage"
    r")\b",
    re.I,
)
NOT_WINE = re.compile(r"\b(chti|blonde|beer|lemonade|vegan|medal|world beer)\b", re.I)
JUNK_NAME = re.compile(
    r"\b(survey cafe|wilson street|bonita|honita|llc|davie|invoice|10530|print name|fintech)\b",
    re.I,
)
HINT = re.compile(
    r"\b("
    r"veuve|pinot|sancerre|chardonnay|cabernet|malbec|brouilly|chateau|château|"
    r"cotes|côtes|gigondas|margaux|emilion|provence|brut|ros[eé]|grigio|blaye|"
    r"chassagne|montrachet|sparkling|sauvignon|merlot|bordeaux|rhone|rhône|"
    r"annamia|parisot|cahors|blanc|wine spots|long valley|sergent"
    r")\b",
    re.I,
)
WHITE = re.compile(
    r"\b(blanc|white|chardonnay|grigio|sancerre|sparkling|brut|prosecco|sauvignon)\b",
    re.I,
)
ROSE = re.compile(r"\bros(?:e|é)\b", re.I)
MESSY = re.compile(r"\b(bil|joner|parivot|proatig|93pts|pts|if sg|0\.5)\b", re.I)
CANONICAL = (
    ("veuveparisot", "Veuve Parisot Sparkling Brut"),
    ("parisot", "Veuve Parisot Sparkling Brut"),
    ("villaloren", "Pinot Grigio Delle Venezie Villa Loren"),
    ("annamia", "Pinot Grigio ANNAMIA"),
    ("paradiso", "Pinot Grigio Paradiso"),
    ("paradogso", "Pinot Grigio Paradiso"),
    ("terreblanche", "Chateau Terre Blanche"),
    ("chassagne", "Chassagne-Montrachet Red Les Voillenots Dessous"),
    ("petitmangot", "St Emilion Grand Cru Chateau Petit Mangot"),
    ("anthelme", "Cotes du Rhone Chevalier D'Anthelme"),
    ("pougelon", "Brouilly AOP Chateau de Pougelon"),
    ("pelvillain", "Malbec Chateau du Port Tradition"),
    ("chateauduport", "Malbec Chateau du Port Tradition"),
    ("winespots", "Cabernet Sauvignon Wine Spots"),
    ("stcroix", "Chateau St Croix Cotes de Provence Prestige Rose"),
    ("cotendeprovence", "Chateau St Croix Cotes de Provence Prestige Rose"),
    ("cotesdeprovence", "Chateau St Croix Cotes de Provence Prestige Rose"),
    ("lavoie", "Cotes Blaye Chateau la Voie"),
    ("gigondas", "Gigondas Les Pierres de Vatlat"),
    ("cussean", "Margaux Chateau Cussean"),
    ("sancerre", "Sancerre Sergent du Roy"),
)


def _fold(value: str) -> str:
    text = str(value or "").lower()
    for src, dst in (("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("ô", "o"), ("ç", "c"), ("ü", "u"), ("î", "i")):
        text = text.replace(src, dst)
    return re.sub(r"[^a-z0-9]+", "", text)


def _title(text: str) -> str:
    words = []
    for raw in re.sub(r"\s+", " ", text).strip(" -|/").split():
        token = raw.strip("«»\"'")
        if not token:
            continue
        if token.isupper() and len(token) <= 3:
            words.append(token)
        else:
            words.append(token[:1].upper() + token[1:])
    return " ".join(words)


def _join_broken_letters(text: str) -> str:
    tokens = str(text or "").split()
    if not tokens:
        return ""
    short = sum(1 for token in tokens if len(token) <= 2)
    if short / len(tokens) < 0.45:
        return " ".join(tokens)
    joined: list[str] = []
    buf = ""
    for token in tokens:
        if token.isdigit() or PACK.search(token) or SKU.search(token):
            if buf:
                joined.append(buf)
                buf = ""
            joined.append(token)
            continue
        if len(token) <= 2 and token.isalpha():
            buf += token
            continue
        if buf:
            joined.append(buf)
            buf = ""
        joined.append(token)
    if buf:
        joined.append(buf)
    return " ".join(joined)


def clean_wine_name(raw: str) -> str:
    text = _join_broken_letters(raw)
    text = re.sub(r"\bBrat\b", "Brut", text)
    text = SKU.sub(" ", text)
    text = PACK.sub(" ", text)
    text = PRICE.sub(" ", text)
    text = re.sub(r"\bQty\s+\d+(?:\.\d+)?\b", " ", text, flags=re.I)
    text = re.sub(r"\bx\s*\d+\b", " ", text, flags=re.I)
    text = re.sub(r"[|•·]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -|/.,")
    if YEAR.search(text):
        year = YEAR.search(text).group(1)
        text = YEAR.sub(" ", text)
        text = re.sub(r"\s+", " ", text).strip(" -|/.,")
        if year not in text:
            text = f"{text} {year}".strip()
    return _title(text)


def infer_color(name: str) -> str:
    if ROSE.search(name):
        return "rose"
    if WHITE.search(name):
        return "white"
    return "red"


def infer_vintage(name: str) -> str:
    match = YEAR.search(name or "")
    return match.group(1) if match else ""


def extract_wine_names(text: str) -> list[str]:
    blob = _join_broken_letters(" ".join(str(text or "").split()))
    blob = SKU.sub(" | ", blob)
    blob = PACK.sub(" | ", blob)
    blob = re.sub(r"\b\d+\s*BTL\b", " | ", blob, flags=re.I)
    names: list[str] = []
    seen: set[str] = set()
    for chunk in re.split(r"[|]", blob):
        if NOT_WINE.search(chunk):
            continue
        if SKIP.search(chunk) and not HINT.search(chunk):
            continue
        if not HINT.search(chunk):
            continue
        name = canonicalize_wine_name(clean_wine_name(chunk).lstrip("+ ").strip())
        if not name:
            continue
        key = _fold(re.sub(r"20\d{2}", "", name))
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def canonicalize_wine_name(name: str) -> str | None:
    key = _fold(name)
    if "longvalley" in key:
        if "cabernet" in key or "auvignon" in key:
            return "Long Valley Ranch Cabernet Sauvignon"
        if "chardonn" in key:
            return "Long Valley Ranch Chardonnay"
    for needle, label in CANONICAL:
        if needle in key:
            return label
    words = name.split()
    if len(words) > 10:
        name = " ".join(words[:10])
    if not _good_label(name) or MESSY.search(name):
        return None
    return name


def _good_label(name: str) -> bool:
    if not HINT.search(name):
        return False
    if JUNK_NAME.search(name) or NOT_WINE.search(name) or "\\" in name:
        return False
    words = [part for part in re.split(r"\s+", name) if part and not YEAR.fullmatch(part)]
    if len(words) < 2:
        return False
    short = sum(1 for word in words if len(re.sub(r"[^A-Za-z]", "", word)) <= 2)
    if short / len(words) > 0.3:
        return False
    letters = sum(ch.isalpha() for ch in name)
    return letters >= 10


def _existing_wine(db: Session, name: str) -> Product | None:
    want = _fold(re.sub(r"20\d{2}", "", name))
    if not want:
        return None
    for product in db.query(Product).filter(Product.category == "wine").all():
        have = _fold(re.sub(r"20\d{2}", "", product.name))
        if have == want:
            return product
        producer = _fold((product.wine.producer if product.wine else "") + product.name)
        if producer == want:
            return product
    return None


def _sku_for(name: str) -> str:
    slug = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:48]
    return f"WINE-{slug or 'LABEL'}"


def add_wine_label(db: Session, name: str, source: str = "") -> Product | None:
    label = clean_wine_name(name)
    if len(label) < 8:
        return None
    existing = _existing_wine(db, label)
    if existing:
        return existing
    sku = _sku_for(label)
    if db.query(Product).filter(Product.sku == sku).first():
        sku = f"{sku}-{db.query(Product).count() + 1}"
    product = Product(
        sku=sku,
        name=label,
        category="wine",
        base_unit="ml",
        current_cost=Decimal("0"),
        notes=(f"Ordered from {source}" if source else "Ordered wine"),
    )
    db.add(product)
    db.flush()
    db.add(
        WineProfile(
            product_id=product.id,
            producer="",
            vintage=infer_vintage(label),
            color=infer_color(label),
            bottle_size_ml=750,
            glass_pour_ml=150,
            bin_location="",
            par_bottles=Decimal("0"),
            list_type="cellar",
        )
    )
    db.flush()
    return product


def _paperless_text(invoice: Invoice, token: str) -> str:
    if not token or not invoice.paperless_id:
        return ""
    base = settings.paperless_base_url.rstrip("/")
    try:
        response = httpx.get(
            f"{base}/api/documents/{invoice.paperless_id}/",
            headers={"Authorization": f"Token {token}"},
            timeout=8.0,
        )
        if response.status_code != 200:
            return ""
        return str(response.json().get("content") or "")
    except Exception:
        return ""


def wine_documents(db: Session, fetch_paperless: bool = True) -> list[dict]:
    token = access_token_for(db, "paperless") if fetch_paperless else ""
    rows = []
    invoices = (
        db.query(Invoice)
        .filter(Invoice.invoice_type == "wine")
        .order_by(Invoice.issued_on.desc(), Invoice.id.desc())
        .all()
    )
    for invoice in invoices:
        lines = "\n".join(line.raw_description for line in invoice.lines if line.raw_description)
        remote = _paperless_text(invoice, token) if token else ""
        text = "\n".join(part for part in (invoice.title, lines, remote) if part)
        supplier = invoice.supplier.name if invoice.supplier else "Wine house"
        rows.append({"invoice": invoice, "text": text, "supplier": supplier})
    return rows


def _delete_wine(db: Session, product: Product) -> None:
    if product.wine:
        db.delete(product.wine)
    db.delete(product)


def scrub_junk_wine_labels(db: Session) -> int:
    """Drop OCR junk and collapse duplicate ordered wines. Never touches quantities."""
    removed = 0
    kept: dict[str, Product] = {}
    for product in db.query(Product).filter(Product.category == "wine").all():
        if product.sku.startswith(("SB-", "PN-", "CHAMP-", "HOUSE-")):
            continue
        if not str(product.notes or "").startswith("Ordered"):
            continue
        if on_hand(db, product.id) > 0:
            continue
        label = canonicalize_wine_name(product.name)
        if not label:
            _delete_wine(db, product)
            removed += 1
            continue
        key = _fold(re.sub(r"20\d{2}", "", label))
        other = kept.get(key) or _existing_wine(db, label)
        if other and other.id != product.id:
            _delete_wine(db, product)
            removed += 1
            continue
        product.name = label
        if product.wine:
            product.wine.color = infer_color(label)
            product.wine.vintage = infer_vintage(label) or product.wine.vintage
        kept[key] = product
    if removed:
        db.commit()
    return removed


def on_hand(db: Session, product_id: int):
    from sqlalchemy import func, select

    from app.models import StockMove

    total = db.scalar(select(func.coalesce(func.sum(StockMove.qty_base), 0)).where(StockMove.product_id == product_id))
    return Decimal(total or 0)


def import_ordered_wines(db: Session, documents: list[dict] | None = None, fetch_paperless: bool = True) -> dict:
    """Create cellar labels for every wine on a purchase ticket. Never writes a quantity."""
    created = 0
    seen = 0
    removed = scrub_junk_wine_labels(db)
    docs = documents if documents is not None else wine_documents(db, fetch_paperless=fetch_paperless)
    for doc in docs:
        supplier = str(doc.get("supplier") or "")
        for name in extract_wine_names(str(doc.get("text") or "")):
            seen += 1
            before = _existing_wine(db, name)
            product = add_wine_label(db, name, source=supplier)
            if product is not None and before is None:
                created += 1
    db.commit()
    return {"created": created, "seen": seen, "removed": removed, "labels": db.query(WineProfile).count()}
