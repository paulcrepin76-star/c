from decimal import Decimal

from app.db import SessionLocal
from app.services import on_hand_base, wine_rows
from app.wines import extract_wine_names, import_ordered_wines


PG_OCR = """
PG Fine Wines Invoice
EDFR-SW-0602... Veuve Parisot Sparkling Brut 12/750
VLUS-W-0201TT Pinot Grigio Delle Venezie "Villa Loren" 2024 12x750
PBFR-W-S20TT+ Sancerre White Sergent du Roy 2024 12 X750
BRUS-W-2024TT Pinot Grigio ANNAMIA Screw Top 12/750
CRFR-R6-2022TT Chateau Terre Blanche 2022 RED 6/750
EDFR-B330-24 CHTI Blonde Alc 6.4% 6X4 24/330 Vegan Beer Awards
DWSB-R6-2022B Chassagne-Montrachet Red Les Voillenots Dessous 2023 6X750
YMRF-R-40021TT St Emilion Grand Cru Chateau Petit Mangot 12x750 2022
DWIFR-R-2024T Cotes du Rhone Chevalier D'Anthelme 2024 12x750
VDFR-R-7001 Brouilly AOP Chateau de Pougelon 2020 12/750
CALUS-R-31010 Cabernet Sauvignon Wine Spots Alexander Valley 2021 12/750
SVCA-W-650010 Long Valley Ranch Chardonnay 12/750
JONFR-RO-StC Chateau St Croix Cotes de Provence Prestige Rose 2023 12x750
Classic Lemon Lime French Lemonade BLUE 24x330
Sauvignon Blanc 2024 x12
"""


def test_messy_ocr_collapses_to_real_label():
    names = extract_wine_names("6 BIL Veuve Parisot Sparkling B Rut 12/750 JONER RON C Chateau St Croix Cotes de Provence Prestige Rose 2023 12x750")
    assert "Veuve Parisot Sparkling Brut" in names
    assert any("St Croix" in name and "Provence" in name for name in names)


def test_extract_wine_names_skips_address_junk():
    names = extract_wine_names("PG Fine Wines invoice Survey Cafe LLC 10530 Wilson Street Bonita Springs")
    assert names == []


def test_extract_wine_names_skips_beer_and_qty():
    names = extract_wine_names(PG_OCR)
    assert any("Veuve Parisot" in name for name in names)
    assert any("Pinot Grigio" in name and "Villa Loren" in name for name in names)
    assert any("Sancerre" in name for name in names)
    assert any("Provence" in name and "Rose" in name for name in names)
    assert all("CHTI" not in name and "Lemonade" not in name for name in names)
    assert all("12/750" not in name and "x12" not in name.lower() for name in names)


def test_import_ordered_wines_adds_names_without_quantity():
    db = SessionLocal()
    try:
        before = {row["product"].name for row in wine_rows(db)}
        result = import_ordered_wines(
            db,
            documents=[{"text": PG_OCR, "supplier": "PG Fine Wines"}],
            fetch_paperless=False,
        )
        assert result["created"] >= 6
        rows = wine_rows(db)
        veuve = next(row for row in rows if "Veuve Parisot" in row["product"].name)
        assert veuve["on_hand_bottles"] == 0
        assert veuve["profile"].par_bottles == 0
        assert on_hand_base(db, veuve["product"].id) == Decimal("0")
        assert "Ordered from PG Fine Wines" in veuve["product"].notes
        assert "Sauvignon Blanc" in before
        assert {row["product"].name for row in rows if row["product"].name == "Sauvignon Blanc"}
    finally:
        db.close()
