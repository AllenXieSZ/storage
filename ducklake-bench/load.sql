-- 加载 SF100 核心表到 DuckLake(A) 和 S3 Tables(C)
-- 占位符: __BUCKET__ __TBARN__ __REGION__
INSTALL ducklake; LOAD ducklake;
INSTALL postgres;  LOAD postgres;
INSTALL httpfs;    LOAD httpfs;
INSTALL iceberg;   LOAD iceberg;
CREATE OR REPLACE SECRET s3sec (TYPE s3, PROVIDER credential_chain, REGION '__REGION__');

ATTACH '/home/ec2-user/bench/tpcds_sf100.duckdb' AS src (READ_ONLY);

-- A: DuckLake (postgres catalog + S3 数据)
ATTACH 'ducklake:postgres:dbname=ducklake_catalog host=127.0.0.1 user=dl password=dl' AS dl
  (DATA_PATH 's3://__BUCKET__/ducklake/');
CREATE SCHEMA IF NOT EXISTS dl.bench;

-- C: S3 Tables
ATTACH '__TBARN__' AS s3t (TYPE iceberg, ENDPOINT_TYPE s3_tables);
CREATE SCHEMA IF NOT EXISTS s3t.bench;

-- 计时: A 组加载
.timer on
.print '===== LOAD A: DuckLake ====='
CREATE TABLE dl.bench.store_sales   AS SELECT * FROM src.store_sales;
CREATE TABLE dl.bench.catalog_sales AS SELECT * FROM src.catalog_sales;
CREATE TABLE dl.bench.web_sales     AS SELECT * FROM src.web_sales;
CREATE TABLE dl.bench.inventory     AS SELECT * FROM src.inventory;
CREATE TABLE dl.bench.date_dim      AS SELECT * FROM src.date_dim;
CREATE TABLE dl.bench.item          AS SELECT * FROM src.item;
CREATE TABLE dl.bench.customer      AS SELECT * FROM src.customer;

.print '===== LOAD C: S3 Tables ====='
CREATE TABLE s3t.bench.store_sales   AS SELECT * FROM src.store_sales;
CREATE TABLE s3t.bench.catalog_sales AS SELECT * FROM src.catalog_sales;
CREATE TABLE s3t.bench.web_sales     AS SELECT * FROM src.web_sales;
CREATE TABLE s3t.bench.inventory     AS SELECT * FROM src.inventory;
CREATE TABLE s3t.bench.date_dim      AS SELECT * FROM src.date_dim;
CREATE TABLE s3t.bench.item          AS SELECT * FROM src.item;
CREATE TABLE s3t.bench.customer      AS SELECT * FROM src.customer;

.print '===== 行数校验 ====='
SELECT 'A_store_sales' k, count(*) c FROM dl.bench.store_sales
UNION ALL SELECT 'C_store_sales', count(*) FROM s3t.bench.store_sales;
