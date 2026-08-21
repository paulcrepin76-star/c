-- Add the `resto` Postgres database as a second Metabase data source.
-- Host: resto-postgres (or your Unraid IP), port 5432 internally / 5433 on the host.
-- Database: resto  User: resto

-- Food / wine / beverage cost, last 7 days
SELECT
  si.costing_group,
  SUM(s.revenue) AS sales,
  SUM(s.qty * si.selling_price) AS listed_sales,
  COUNT(*) AS tickets
FROM sales s
JOIN sellable_items si ON si.id = s.sellable_item_id
WHERE s.sold_at >= NOW() - INTERVAL '7 days'
GROUP BY 1
ORDER BY 2 DESC;

-- Cellar: on-hand bottles and value
SELECT
  p.name,
  wp.producer,
  wp.vintage,
  wp.color,
  wp.bin_location,
  wp.par_bottles,
  ROUND(COALESCE(SUM(sm.qty_base), 0) / wp.bottle_size_ml, 2) AS bottles_on_hand,
  ROUND(
    (COALESCE(SUM(sm.qty_base), 0) / wp.bottle_size_ml) * (p.current_cost * wp.bottle_size_ml),
    2
  ) AS cellar_value
FROM products p
JOIN wine_profiles wp ON wp.product_id = p.id
LEFT JOIN stock_moves sm ON sm.product_id = p.id
WHERE p.category = 'wine'
GROUP BY p.id, p.name, p.current_cost, wp.producer, wp.vintage, wp.color, wp.bin_location, wp.par_bottles, wp.bottle_size_ml
ORDER BY wp.color, p.name;

-- Wines below par
SELECT *
FROM (
  SELECT
    p.name,
    wp.bin_location,
    wp.par_bottles,
    ROUND(COALESCE(SUM(sm.qty_base), 0) / wp.bottle_size_ml, 2) AS bottles_on_hand
  FROM products p
  JOIN wine_profiles wp ON wp.product_id = p.id
  LEFT JOIN stock_moves sm ON sm.product_id = p.id
  GROUP BY p.name, wp.bin_location, wp.par_bottles, wp.bottle_size_ml
) cellar
WHERE bottles_on_hand < par_bottles
ORDER BY bottles_on_hand;

-- Theoretical wine usage from sales (glasses + bottles)
SELECT
  p.name,
  wp.vintage,
  SUM(s.qty * si.serving_qty) AS ml_sold,
  ROUND(SUM(s.qty * si.serving_qty) / wp.bottle_size_ml, 2) AS bottles_sold_equivalent,
  SUM(s.revenue) AS wine_sales
FROM sales s
JOIN sellable_items si ON si.id = s.sellable_item_id
JOIN products p ON p.id = si.product_id
JOIN wine_profiles wp ON wp.product_id = p.id
WHERE s.sold_at >= DATE_TRUNC('month', NOW())
GROUP BY p.name, wp.vintage, wp.bottle_size_ml
ORDER BY wine_sales DESC;

-- Invoice spend by supplier this month
SELECT
  COALESCE(sup.name, 'Unknown') AS supplier,
  i.invoice_type,
  COUNT(*) AS invoices,
  SUM(i.total) AS spend
FROM invoices i
LEFT JOIN suppliers sup ON sup.id = i.supplier_id
WHERE i.issued_on >= DATE_TRUNC('month', NOW())
GROUP BY 1, 2
ORDER BY 4 DESC;

-- Purchasing / price intelligence: latest comparable unit cost by supplier
SELECT
  p.name AS product,
  COALESCE(p.purchasing_category, p.category) AS category,
  s.name AS supplier,
  pp.pack_qty,
  pp.pack_unit,
  pp.pack_price,
  pp.unit_cost_compare AS cost_per_compare_unit,
  p.compare_unit,
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

-- Products cheaper at another vendor than the volume supplier
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
