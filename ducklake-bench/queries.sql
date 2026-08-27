-- 查询基准: A(DuckLake) vs C(S3 Tables)  同引擎 DuckDB
-- 占位符 __SCHEMA__ 由外部 sed 换成 dl.bench 或 s3t.bench
-- 5 条扫描/聚合/JOIN 密集查询, 覆盖大表
.timer on

-- Q1: store_sales 全表聚合
SELECT ss_store_sk, count(*) cnt, sum(ss_sales_price) rev
FROM __SCHEMA__.store_sales
GROUP BY ss_store_sk ORDER BY rev DESC NULLS LAST LIMIT 20;

-- Q2: store_sales JOIN date_dim 带过滤 (谓词下推)
SELECT d_year, d_moy, sum(ss_ext_sales_price) total
FROM __SCHEMA__.store_sales ss JOIN __SCHEMA__.date_dim d ON ss.ss_sold_date_sk=d.d_date_sk
WHERE d_year=2001
GROUP BY d_year, d_moy ORDER BY d_moy;

-- Q3: 三表 JOIN (store_sales x item x date_dim)
SELECT i_category, sum(ss_net_profit) profit
FROM __SCHEMA__.store_sales ss
  JOIN __SCHEMA__.item i ON ss.ss_item_sk=i.i_item_sk
  JOIN __SCHEMA__.date_dim d ON ss.ss_sold_date_sk=d.d_date_sk
WHERE d_year=2000
GROUP BY i_category ORDER BY profit DESC NULLS LAST LIMIT 10;

-- Q4: inventory 大表聚合 (399M 行)
SELECT inv_warehouse_sk, avg(inv_quantity_on_hand) avgq
FROM __SCHEMA__.inventory
GROUP BY inv_warehouse_sk ORDER BY avgq DESC NULLS LAST LIMIT 15;

-- Q5: catalog+web+store 三大 sales union 汇总
SELECT 'store' ch, count(*) c, sum(ss_sales_price) s FROM __SCHEMA__.store_sales
UNION ALL SELECT 'catalog', count(*), sum(cs_sales_price) FROM __SCHEMA__.catalog_sales
UNION ALL SELECT 'web', count(*), sum(ws_sales_price) FROM __SCHEMA__.web_sales;
