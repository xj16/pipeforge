-- Example analytical queries against the pipeforge star schema.
-- These run unchanged on SQLite (data/warehouse/pipeforge.db) or Postgres.
--
--   sqlite3 data/warehouse/pipeforge.db < sql/example_queries.sql

-- 1. Revenue by product category (the headline metric).
SELECT p.category, ROUND(SUM(f.revenue), 2) AS revenue
FROM fact_sales f
JOIN dim_product p ON f.product_key = p.product_key
GROUP BY p.category
ORDER BY revenue DESC;

-- 2. Top 5 products by units sold.
SELECT p.stock_code, p.description, SUM(f.quantity) AS units
FROM fact_sales f
JOIN dim_product p ON f.product_key = p.product_key
GROUP BY p.stock_code, p.description
ORDER BY units DESC
LIMIT 5;

-- 3. Revenue by country.
SELECT c.country, ROUND(SUM(f.revenue), 2) AS revenue
FROM fact_sales f
JOIN dim_customer c ON f.customer_key = c.customer_key
GROUP BY c.country
ORDER BY revenue DESC;

-- 4. Monthly revenue trend.
SELECT d.year, d.month, ROUND(SUM(f.revenue), 2) AS revenue
FROM fact_sales f
JOIN dim_date d ON f.date_key = d.date_key
GROUP BY d.year, d.month
ORDER BY d.year, d.month;

-- 5. Weekend vs weekday revenue split.
SELECT d.is_weekend, ROUND(SUM(f.revenue), 2) AS revenue
FROM fact_sales f
JOIN dim_date d ON f.date_key = d.date_key
GROUP BY d.is_weekend;

-- 6. Data-quality: how many rows were quarantined and why?
SELECT quarantine_reason, COUNT(*) AS rows
FROM quarantine
GROUP BY quarantine_reason
ORDER BY rows DESC;
