-- Survey Cafe Metabase questions.
-- Host: postgres (from Metabase) or 100.116.48.120 port 5433
-- Database: resto

-- name: YTD sales
-- display: scalar
SELECT COALESCE(SUM(revenue), 0) AS ytd_sales
FROM sales
WHERE sold_at >= DATE_TRUNC('year', NOW());

-- name: YTD tickets
-- display: scalar
SELECT COUNT(DISTINCT square_order_id) AS ytd_tickets
FROM sales
WHERE sold_at >= DATE_TRUNC('year', NOW())
  AND square_order_id <> ''
  AND square_order_id NOT LIKE 'demo-%';

-- name: Invoice spend YTD
-- display: scalar
SELECT COALESCE(SUM(total), 0) AS invoice_spend
FROM invoices
WHERE issued_on >= DATE_TRUNC('year', NOW())::date;

-- name: Recipes on file
-- display: scalar
SELECT COUNT(*) AS recipes FROM recipes;

-- name: Sales by day this year
-- display: line
SELECT
  DATE_TRUNC('day', sold_at)::date AS day,
  SUM(revenue) AS sales,
  COUNT(*) AS line_items
FROM sales
WHERE sold_at >= DATE_TRUNC('year', NOW())
GROUP BY 1
ORDER BY 1;

-- name: Sales by costing group YTD
-- display: bar
SELECT
  si.costing_group,
  SUM(s.revenue) AS sales,
  COUNT(*) AS tickets
FROM sales s
JOIN sellable_items si ON si.id = s.sellable_item_id
WHERE s.sold_at >= DATE_TRUNC('year', NOW())
GROUP BY 1
ORDER BY 2 DESC;

-- name: Top selling items YTD
-- display: table
SELECT
  si.name,
  si.costing_group,
  SUM(s.qty) AS qty,
  SUM(s.revenue) AS sales
FROM sales s
JOIN sellable_items si ON si.id = s.sellable_item_id
WHERE s.sold_at >= DATE_TRUNC('year', NOW())
GROUP BY si.name, si.costing_group
ORDER BY sales DESC
LIMIT 40;

-- name: Invoice spend by supplier YTD
-- display: bar
SELECT
  COALESCE(sup.name, 'Unknown') AS supplier,
  i.invoice_type,
  COUNT(*) AS invoices,
  SUM(i.total) AS spend
FROM invoices i
LEFT JOIN suppliers sup ON sup.id = i.supplier_id
WHERE i.issued_on >= DATE_TRUNC('year', NOW())::date
GROUP BY 1, 2
ORDER BY 4 DESC;

-- name: Invoice spend this month
-- display: table
SELECT
  COALESCE(sup.name, 'Unknown') AS supplier,
  i.invoice_type,
  COUNT(*) AS invoices,
  SUM(i.total) AS spend
FROM invoices i
LEFT JOIN suppliers sup ON sup.id = i.supplier_id
WHERE i.issued_on >= DATE_TRUNC('month', NOW())::date
GROUP BY 1, 2
ORDER BY 4 DESC;

-- name: Cellar bottles and value
-- display: table
SELECT
  p.name,
  wp.producer,
  wp.vintage,
  wp.color,
  wp.bin_location,
  wp.par_bottles,
  ROUND(COALESCE(SUM(sm.qty_base), 0) / NULLIF(wp.bottle_size_ml, 0), 2) AS bottles_on_hand,
  ROUND(COALESCE(SUM(sm.qty_base), 0) * p.current_cost, 2) AS cellar_value
FROM products p
JOIN wine_profiles wp ON wp.product_id = p.id
LEFT JOIN stock_moves sm ON sm.product_id = p.id
WHERE p.category = 'wine'
GROUP BY p.id, p.name, p.current_cost, wp.producer, wp.vintage, wp.color, wp.bin_location, wp.par_bottles, wp.bottle_size_ml
ORDER BY wp.color, p.name;

-- name: Wines below par
-- display: table
SELECT *
FROM (
  SELECT
    p.name,
    wp.bin_location,
    wp.par_bottles,
    ROUND(COALESCE(SUM(sm.qty_base), 0) / NULLIF(wp.bottle_size_ml, 0), 2) AS bottles_on_hand
  FROM products p
  JOIN wine_profiles wp ON wp.product_id = p.id
  LEFT JOIN stock_moves sm ON sm.product_id = p.id
  GROUP BY p.name, wp.bin_location, wp.par_bottles, wp.bottle_size_ml
) cellar
WHERE bottles_on_hand < par_bottles
ORDER BY bottles_on_hand;

-- name: Wine sales this month
-- display: table
SELECT
  p.name,
  wp.vintage,
  SUM(s.qty * si.serving_qty) AS ml_sold,
  ROUND(SUM(s.qty * si.serving_qty) / NULLIF(wp.bottle_size_ml, 0), 2) AS bottles_sold_equivalent,
  SUM(s.revenue) AS wine_sales
FROM sales s
JOIN sellable_items si ON si.id = s.sellable_item_id
JOIN products p ON p.id = si.product_id
JOIN wine_profiles wp ON wp.product_id = p.id
WHERE s.sold_at >= DATE_TRUNC('month', NOW())
GROUP BY p.name, wp.vintage, wp.bottle_size_ml
ORDER BY wine_sales DESC;

-- name: Latest purchase prices
-- display: table
SELECT
  p.name AS product,
  COALESCE(p.purchasing_category, p.category) AS category,
  s.name AS supplier,
  pp.pack_qty,
  pp.pack_unit,
  pp.pack_price,
  pp.unit_cost_compare AS cost_per_compare_unit,
  p.compare_unit,
  pp.source,
  pp.purchased_on
FROM purchase_prices pp
JOIN products p ON p.id = pp.product_id
JOIN suppliers s ON s.id = pp.supplier_id
WHERE pp.id IN (
  SELECT MAX(id)
  FROM purchase_prices
  GROUP BY product_id, supplier_id
)
ORDER BY p.name, cost_per_compare_unit;

-- name: Cheaper at another vendor
-- display: table
SELECT
  p.name,
  cur.supplier AS current_supplier,
  cur.unit_cost AS current_cost,
  best.supplier AS best_supplier,
  best.unit_cost AS best_cost,
  ROUND((cur.unit_cost - best.unit_cost) / NULLIF(cur.unit_cost, 0) * 100, 1) AS pct_cheaper
FROM (
  SELECT DISTINCT ON (pp.product_id)
    pp.product_id,
    s.name AS supplier,
    pp.unit_cost_compare AS unit_cost
  FROM purchase_prices pp
  JOIN suppliers s ON s.id = pp.supplier_id
  ORDER BY pp.product_id, pp.purchased_on DESC NULLS LAST, pp.id DESC
) cur
JOIN (
  SELECT DISTINCT ON (pp.product_id)
    pp.product_id,
    s.name AS supplier,
    pp.unit_cost_compare AS unit_cost
  FROM purchase_prices pp
  JOIN suppliers s ON s.id = pp.supplier_id
  ORDER BY pp.product_id, pp.unit_cost_compare ASC, pp.id DESC
) best ON best.product_id = cur.product_id
JOIN products p ON p.id = cur.product_id
WHERE best.unit_cost < cur.unit_cost
ORDER BY pct_cheaper DESC;

-- name: Overnight price checks
-- display: table
SELECT
  finished_at,
  checked,
  updated,
  unchanged,
  unavailable,
  needs_reauth
FROM collector_runs
ORDER BY id DESC
LIMIT 30;

-- name: Connected services
-- display: table
SELECT name, status, updated_at
FROM connections
ORDER BY name;

-- name: Recipe cost snapshots
-- display: table
SELECT captured_on, name, cost
FROM cost_snapshots
WHERE kind = 'recipe'
ORDER BY captured_on DESC, name
LIMIT 80;
