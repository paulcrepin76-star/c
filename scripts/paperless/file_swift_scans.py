#!/usr/bin/env python3
"""Split mixed Swift Paperless scans into one invoice per page and file them.

Run inside the Paperless webserver container:
  python3 /tmp/file_swift_scans.py --dry-run
  python3 /tmp/file_swift_scans.py
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

os.chdir("/usr/src/paperless/src")
sys.path.insert(0, "/usr/src/paperless/src")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "paperless.settings")

import django

django.setup()

import pikepdf  # noqa: E402
from django.db.models import Q  # noqa: E402
from documents.data_models import ConsumableDocument, DocumentMetadataOverrides, DocumentSource  # noqa: E402
from documents.models import Correspondent, Document, DocumentType, StoragePath, Tag  # noqa: E402
from documents.tasks import consume_file  # noqa: E402

SCAN_IDS = (1446, 1447, 1448)
VENDORS = {
    "restaurant-depot": ("Restaurant Depot", "Vendor Invoice", False),
    "sams-club": ("Sam's Club", "Vendor Invoice", False),
    "st-armands": ("St. Armands Baking Company", "Vendor Invoice", False),
    "aldi": ("ALDI", "Vendor Invoice", False),
    "pg-fine-wines": ("PG Fine Wines", "Wine Invoice", False),
    "stans-coffee": ("Stan's Coffee", "Vendor Invoice", False),
    "vistaserv": ("VistaServ", "Vendor Invoice", False),
    "publix": ("Publix", "Receipt", False),
}


def squeezed(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def classify(text: str) -> tuple[str, dict, bool, bool]:
    low = text.lower()
    sq = squeezed(text)
    scores: dict[str, int] = {}

    def add(name: str, n: int = 1) -> None:
        scores[name] = scores.get(name, 0) + n

    if "klld" in sq or "customer(sale)" in sq or "frenchrestaurant" in sq or "sic21" in sq:
        add("restaurant-depot", 3)
    if "unitsentered" in sq or "casesentered" in sq or "tom sundried" in low or "op277382" in sq:
        add("restaurant-depot", 2)
    if "samsclub" in sq or "sansclub" in sq or "samscash" in sq or "sanscash" in sq:
        add("sams-club", 3)
    if "instantsavings" in sq or "youreasavings" in sq or "inst su" in low:
        add("sams-club", 2)
    if "visatend" in sq or "totalpurchase" in sq:
        add("sams-club", 1)
    if re.search(r"\baldi\b", low) or "help.aldi" in low:
        add("aldi", 3)
    if "pgfinewines" in sq or "pgfinewine" in sq or "veuveparisot" in sq:
        add("pg-fine-wines", 3)
    if "pg pine wines" in low or "po vine wines" in low:
        add("pg-fine-wines", 2)
    if "armands" in sq or "thickdeli" in sq or re.search(r"\binv8\d+", low):
        add("st-armands", 2)
    if "stanscoffee" in sq or "stanscof" in sq or "coffeeandfood" in sq or "lehigh" in sq or "roasters" in sq:
        add("stans-coffee", 3)
    if "vistaserv" in sq or "dishmachines" in sq:
        add("vistaserv", 3)
    if re.search(r"\bpublix\b", low):
        add("publix", 3)

    words = re.findall(r"[A-Za-z]{3,}", text)
    letters = sum(ch.isalpha() for ch in text)
    faded = len(words) < 15 or letters < 80 or (len(text) >= 400 and letters / max(len(text), 1) < 0.12)
    vendor = max(scores, key=scores.get) if scores else "unknown"
    confident = (not faded) and scores.get(vendor, 0) >= 1 and vendor != "unknown"
    return vendor, scores, faded, confident


def page_text(pdf_path: str, page: int) -> str:
    result = subprocess.run(
        ["pdftotext", "-f", str(page), "-l", str(page), "-layout", pdf_path, "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout or ""


def parse_date(text: str):
    patterns = [
        re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b"),
        re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    ]
    for match in patterns[0].finditer(text):
        month, day, year = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if year < 100:
            year += 2000
        if year < 2023 or year > 2027:
            continue
        try:
            return datetime(year, month, day)
        except ValueError:
            continue
    for match in patterns[1].finditer(text):
        year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if year < 2023 or year > 2027:
            continue
        try:
            return datetime(year, month, day)
        except ValueError:
            continue
    return None


def get_or_create_type(name: str) -> DocumentType:
    row = DocumentType.objects.filter(name__iexact=name).first()
    if row:
        return row
    return DocumentType.objects.create(
        name=name,
        match="",
        matching_algorithm=DocumentType.MATCH_NONE,
        is_insensitive=True,
    )


def get_or_create_correspondent(name: str) -> Correspondent:
    row = Correspondent.objects.filter(name__iexact=name).first()
    if row:
        return row
    return Correspondent.objects.create(
        name=name,
        match=name,
        matching_algorithm=Correspondent.MATCH_AUTO,
        is_insensitive=True,
    )


def archive_pdf(document: Document) -> Path:
    path = Path(str(document.archive_path or document.source_path))
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def plan_scans() -> list[dict]:
    planned = []
    for pk in SCAN_IDS:
        document = Document.objects.get(pk=pk)
        pdf = archive_pdf(document)
        pages = document.page_count or 0
        prev = None
        for page in range(1, pages + 1):
            text = page_text(str(pdf), page)
            vendor, scores, faded, confident = classify(text)
            if len(text.strip()) <= 5:
                planned.append(
                    {
                        "source_id": pk,
                        "page": page,
                        "skip": True,
                        "reason": "blank",
                        "vendor": "unknown",
                        "faded": True,
                        "title": "",
                    }
                )
                continue
            if vendor == "unknown" and prev and prev.get("vendor") not in (None, "unknown") and not prev.get("faded"):
                vendor = prev["vendor"]
                confident = False
            needs_review = faded or vendor == "unknown" or not confident
            if vendor == "publix" and faded:
                vendor = "unknown"
                needs_review = True
            label = VENDORS.get(vendor, ("Unknown", "Vendor Invoice", False))[0]
            created = parse_date(text) or document.created
            date_bit = created.strftime("%Y-%m-%d") if hasattr(created, "strftime") else str(created)[:10]
            title = f"{label} {date_bit}" if vendor != "unknown" else f"Scan {date_bit} needs review"
            title = f"{title} ({pk} p{page})"
            item = {
                "source_id": pk,
                "page": page,
                "skip": False,
                "vendor": vendor,
                "label": label if vendor != "unknown" else "",
                "doc_type": VENDORS.get(vendor, ("Unknown", "Vendor Invoice", False))[1],
                "faded": faded,
                "confident": confident,
                "needs_review": needs_review,
                "title": title,
                "created": created,
                "scores": scores,
                "chars": len(text),
                "owner_id": document.owner_id,
            }
            planned.append(item)
            prev = item
    return planned


def file_filename_docs() -> dict:
    utility = get_or_create_type("Utility Bill")
    vendor_invoice = get_or_create_type("Vendor Invoice")
    storage = StoragePath.objects.filter(name__iexact="Survey Cafe Archive").first()
    fpl = get_or_create_correspondent("FPL Bonita Springs")
    chefs = Correspondent.objects.filter(name__iexact="Chef's Warehouse").first() or get_or_create_correspondent(
        "Chef's Warehouse"
    )
    sams = Correspondent.objects.filter(name__iexact="Sam's Club").first()
    updated = {"fpl": 0, "chefs": 0, "sams": 0}
    from django.utils import timezone

    start = timezone.now() - __import__("datetime").timedelta(hours=36)
    today = Document.objects.filter(added__gte=start)
    for document in today:
        title = f"{document.title or ''} {document.original_filename or ''}".lower()
        changed = []
        if "fpl-" in title or title.startswith("fpl"):
            if document.correspondent_id != fpl.id:
                document.correspondent = fpl
                changed.append("correspondent")
            if document.document_type_id != utility.id:
                document.document_type = utility
                changed.append("document_type")
            if storage and document.storage_path_id != storage.id:
                document.storage_path = storage
                changed.append("storage_path")
            if changed:
                document.save(update_fields=changed)
                updated["fpl"] += 1
        elif "chefs-warehouse" in title or "chef's warehouse" in title:
            if chefs and document.correspondent_id != chefs.id:
                document.correspondent = chefs
                changed.append("correspondent")
            if document.document_type_id != vendor_invoice.id:
                document.document_type = vendor_invoice
                changed.append("document_type")
            if storage and document.storage_path_id != storage.id:
                document.storage_path = storage
                changed.append("storage_path")
            if changed:
                document.save(update_fields=changed)
                updated["chefs"] += 1
        elif "sams-club" in title and sams and not document.correspondent_id:
            document.correspondent = sams
            if storage and document.storage_path_id != storage.id:
                document.storage_path = storage
                document.save(update_fields=["correspondent", "storage_path"])
            else:
                document.save(update_fields=["correspondent"])
            updated["sams"] += 1
    return updated


def split_and_consume(planned: list[dict], dry_run: bool) -> list[dict]:
    storage = StoragePath.objects.filter(name__iexact="Survey Cafe Archive").first()
    needs_review = Tag.objects.filter(name__iexact="Needs Review").first()
    types = {name: get_or_create_type(name) for name in ("Vendor Invoice", "Wine Invoice", "Receipt", "Utility Bill")}
    correspondents = {}
    for _slug, (label, _dtype, _) in VENDORS.items():
        correspondents[label] = get_or_create_correspondent(label)

    created = []
    by_source: dict[int, list[dict]] = {}
    for item in planned:
        by_source.setdefault(item["source_id"], []).append(item)

    work = Path(tempfile.mkdtemp(prefix="swift-split-"))
    for source_id, items in by_source.items():
        document = Document.objects.get(pk=source_id)
        pdf = pikepdf.open(str(archive_pdf(document)))
        for item in items:
            if item["skip"]:
                print(f"SKIP blank {source_id} p{item['page']}")
                continue
            page_pdf = work / f"swift-{source_id}-p{item['page']:02d}.pdf"
            out = pikepdf.Pdf.new()
            out.pages.append(pdf.pages[item["page"] - 1])
            out.save(page_pdf)
            print(
                f"{'DRY ' if dry_run else ''}"
                f"{source_id} p{item['page']:02d} vendor={item['vendor']:18s} "
                f"review={item['needs_review']} faded={item['faded']} {item['title']}"
            )
            if dry_run:
                continue
            corr = correspondents.get(item["label"]) if item["label"] else None
            dtype = types.get(item["doc_type"]) or types["Vendor Invoice"]
            tag_ids = []
            if item["needs_review"] and needs_review:
                tag_ids = [needs_review.id]
            overrides = DocumentMetadataOverrides(
                filename=page_pdf.name,
                title=item["title"][:240],
                correspondent_id=corr.id if corr else None,
                document_type_id=dtype.id,
                tag_ids=tag_ids,
                storage_path_id=storage.id if storage else None,
                created=item["created"],
                owner_id=item["owner_id"],
            )
            result = consume_file(
                ConsumableDocument(source=DocumentSource.ApiUpload, original_file=page_pdf),
                overrides,
            )
            new_id = result.get("document_id") if isinstance(result, dict) else getattr(result, "document_id", None)
            created.append({"source_id": source_id, "page": item["page"], "new_id": new_id, "title": item["title"]})
            print(f"  -> document {new_id}")
    return created


def delete_originals(created: list[dict]) -> None:
    if not created:
        print("Not deleting originals; nothing was created.")
        return
    missing = [row for row in created if not row.get("new_id")]
    if missing:
        print(f"Not deleting originals; {len(missing)} page(s) failed to consume.")
        return
    for pk in SCAN_IDS:
        document = Document.objects.filter(pk=pk).first()
        if document:
            document.delete()
            print(f"Deleted combined scan {pk}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-originals", action="store_true")
    args = parser.parse_args()
    planned = plan_scans()
    counts: dict[str, int] = {}
    for item in planned:
        if item.get("skip"):
            counts["blank"] = counts.get("blank", 0) + 1
            continue
        counts[item["vendor"]] = counts.get(item["vendor"], 0) + 1
    print("Scan page plan:", dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))))
    print("Needs review:", sum(1 for item in planned if item.get("needs_review")))
    if args.dry_run:
        split_and_consume(planned, dry_run=True)
        print("Filename docs would be classified (FPL / Chef's / Sam's).")
        return 0
    created = split_and_consume(planned, dry_run=False)
    filed = file_filename_docs()
    print("Filename classify:", filed)
    print(f"Created {len(created)} split documents")
    if not args.keep_originals:
        delete_originals(created)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
