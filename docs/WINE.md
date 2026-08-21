# Wine management

Wine is a first-class part of resto-core. It is not a Mealie recipe.

## What you track

For each label:

- Producer, vintage, color, region, appellation, grape
- Bottle size (750 ml default) and glass pour (150 ml default)
- Bin number and par level
- Last bottle cost
- Glass price and bottle price
- On-hand bottles (from stock moves, not a separate spreadsheet)

Vintage is part of the identity. The 2022 and 2023 Pinot are two products: they were not purchased at the same price.

## Costing

```text
cost per glass = bottle cost × (pour ml / bottle ml)
wine cost %   = cost per glass / selling price
coefficient   = selling price / cost per glass
```

House pour, reserve list, and Champagne use the same formulas. Magnums are just a different `bottle_size_ml`.

## Theoretical vs counted

Square says what was rung. The cellar says what is left.

```text
expected remaining
  = beginning bottles
  + purchased bottles
  - (glasses sold × pour ml + bottles sold × bottle ml) / bottle ml
```

A short count on Sunday night is enough. Enter full bottles; use 0.4 if an open bottle is about 40% full. resto-core writes a `count_adjust` move for the difference.

That difference is the useful number: over-pouring, complimentary glasses, breakage, or a bottle that never made it to the cellar.

## What goes in Mealie

| Item | Where |
| --- | --- |
| Sauvignon Blanc glass / bottle | Wine cellar |
| House red / house white | Wine cellar |
| Beer bottle or keg later | Product costing (same tables) |
| Sangria, spritz, coffee drink | Mealie recipe |
| Coq au vin, wine sauce | Mealie recipe that consumes wine ml |

Sangria example already seeded:

- House red 120 ml
- Brandy 15 ml
- Orange juice 30 ml

The costing engine prices one glass from current purchase costs, then compares it to the Square sangria item.

## Square mapping

Each glass and bottle sellable can store `square_item_id`. n8n sends that id on `/api/sales/import` so names can change on the POS without breaking costing.

Until Square is connected, you can still receive bottles and take counts. The demo week of sales is only there so the dashboard is readable on first boot.

## Suggested Metabase tiles

- Wine cost % this week vs last week
- Cellar value
- Below par (reorder)
- Theoretical bottles used vs counted
- Top 10 wines by margin
- Champagne vs still wine cost %
