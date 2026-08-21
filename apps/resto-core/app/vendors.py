from __future__ import annotations

VENDORS: list[dict] = [
    {
        "slug": "fpl",
        "label": "FPL Bonita Springs",
        "kind": "utility",
        "invoice_type": "utility",
        "email_domain": "fpl.com",
        "login_url": "https://www.fpl.com/my-account.html",
        "blurb": "Electric for the cafe. This login is the FPL business account (24 monthly statements). Two personal FPL accounts are not on this login — finish those with e-bill email.",
        "legacy_names": ["FPL", "Florida Power & Light", "Florida Power and Light", "Florida Power"],
        "match_needles": ["fpl", "florida power"],
        "e_bill_email": "surveycafedowntown@gmail.com",
        "business_statements": 24,
    },
    {
        "slug": "bonita-springs-water",
        "label": "Bonita Springs Water",
        "kind": "utility",
        "invoice_type": "utility",
        "email_domain": "bsu.us",
        "login_url": "https://bsu.us/",
        "blurb": "Water for the Bonita Springs cafe. Paperless files the emailed bill.",
        "legacy_names": ["The Greatest Spring Water", "Water", "Bonita Springs Utilities"],
        "legacy_slugs": ["greatest-spring-water"],
    },
    {
        "slug": "chefs-warehouse",
        "label": "Chef's Warehouse",
        "kind": "food",
        "invoice_type": "food",
        "email_domain": "chefswarehouse.com",
        "login_url": "https://shop.chefswarehouse.com/",
        "blurb": "Food invoices. Codex already pulled the Chef's archive. New bills go to Paperless.",
        "legacy_names": ["Chef Rao's", "The Chefs' Warehouse of Florida, LLC", "The Chefs' Warehouse", "Chefs Warehouse"],
        "match_needles": ["chef's warehouse", "chefs' warehouse", "chefswarehouse"],
    },
    {
        "slug": "sams-club",
        "label": "Sam's Club",
        "kind": "food",
        "invoice_type": "food",
        "email_domain": "samsclub.com",
        "login_url": "https://www.samsclub.com/login",
        "blurb": "Receipts and invoices. Prefer the PDF that lands in Gmail.",
        "legacy_names": [],
    },
    {
        "slug": "costco",
        "label": "Costco",
        "kind": "food",
        "invoice_type": "food",
        "email_domain": "costco.com",
        "login_url": "https://www.costco.com/LogonForm",
        "blurb": "Business Center receipts. Email PDF first, portal only if a bill is missing.",
        "legacy_names": [],
    },
    {
        "slug": "gordon",
        "label": "Gordon Food Service",
        "kind": "food",
        "invoice_type": "food",
        "email_domain": "gfs.com",
        "login_url": "https://order.gfs.com/",
        "blurb": "GFS invoices. Log in on Gordon, then come back here.",
        "legacy_names": ["Gordon"],
    },
    {
        "slug": "restaurant-depot",
        "label": "Restaurant Depot",
        "kind": "food",
        "invoice_type": "food",
        "email_domain": "restaurantdepot.com",
        "login_url": "https://www.restaurantdepot.com/",
        "blurb": "Cash-and-carry. Photograph the receipt or drop the PDF in Paperless. A cheaper case only wins if the monthly saving beats the drive.",
        "legacy_names": ["Rest Depot"],
        "match_needles": ["restaurant depot"],
    },
    {
        "slug": "pg-fine-wines",
        "label": "PG Fine Wines",
        "kind": "wine",
        "invoice_type": "wine",
        "email_domain": "pgfinewines.com",
        "login_url": "",
        "connectable": False,
        "blurb": "Wine house. Photograph the delivery ticket; Paperless files it as a wine invoice.",
        "legacy_names": ["PG Finewines", "PGFine Wines"],
        "match_needles": ["pg fine wines", "pgfinewines"],
    },
    {
        "slug": "aldi",
        "label": "ALDI",
        "kind": "food",
        "invoice_type": "food",
        "email_domain": "aldi.us",
        "login_url": "",
        "connectable": False,
        "blurb": "Grocery receipts. Photograph the ticket. Skip it if the ink is gone.",
        "legacy_names": [],
        "match_needles": ["aldi"],
    },
    {
        "slug": "stans-coffee",
        "label": "Stan's Coffee",
        "kind": "food",
        "invoice_type": "food",
        "email_domain": "",
        "login_url": "",
        "connectable": False,
        "blurb": "Coffee roasting invoices. Photograph the delivery ticket.",
        "legacy_names": ["Stan's Coffee and Food Service", "STANS COFFEE"],
        "match_needles": ["stan's coffee", "stans coffee"],
    },
    {
        "slug": "st-armands",
        "label": "St. Armands Baking Company",
        "kind": "food",
        "invoice_type": "food",
        "email_domain": "",
        "login_url": "",
        "connectable": False,
        "blurb": "Bread invoices. Photograph the ticket or keep the emailed PDF.",
        "legacy_names": ["St Armands Baking Company", "Armands Baking"],
        "match_needles": ["st. armands", "st armands", "armands baking"],
    },
]


def vendor_by_slug(slug: str) -> dict | None:
    for vendor in VENDORS:
        aliases = [vendor["slug"], *(vendor.get("legacy_slugs") or [])]
        if slug in aliases:
            return vendor
    return None


def vendor_names(vendor: dict) -> list[str]:
    names = [vendor["label"], *vendor.get("legacy_names", [])]
    return [name for name in names if name]
