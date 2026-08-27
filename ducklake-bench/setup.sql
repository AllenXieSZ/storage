-- ============ DuckLake vs Iceberg(自管) vs S3 Tables 三方基准 ============
-- 前提: ~/bench/tpcds_sf100.duckdb 已生成 SF100 数据
-- 变量占位符 (脚本里用 sed 替换): __BUCKET__ __TBARN__ __REGION__

INSTALL ducklake; LOAD ducklake;
INSTALL postgres;  LOAD postgres;
INSTALL httpfs;    LOAD httpfs;
INSTALL iceberg;   LOAD iceberg;
INSTALL tpcds;     LOAD tpcds;

-- 用实例 IAM role 的凭证访问 S3
CREATE OR REPLACE SECRET s3secret (TYPE s3, PROVIDER credential_chain, REGION '__REGION__');

-- 源数据 (SF100)
ATTACH '/home/ec2-user/bench/tpcds_sf100.duckdb' AS src (READ_ONLY);

-- ========== A 组: DuckLake (元数据 -> PostgreSQL, 数据 -> S3 Parquet) ==========
ATTACH 'ducklake:postgres:dbname=ducklake_catalog host=127.0.0.1 user=dl password=dl' AS dl
  (DATA_PATH 's3://__BUCKET__/ducklake/');

-- ========== B 组: 自管 Iceberg (DuckDB iceberg 写, 数据+元数据 -> S3) ==========
-- 注: DuckDB iceberg 写支持视版本; 若不支持写, B 组用 DuckDB 原生 parquet + 手动 compaction 模拟
-- (下面 load 脚本单独处理)
