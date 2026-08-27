#!/bin/bash
# 查询基准 runner: A(DuckLake) vs C(S3 Tables), 各 3 轮
export PATH=$PATH:~/.duckdb/cli/latest
cd ~/bench
BUCKET="$1"; TBARN="$2"; REGION="$3"

# 生成 attach 头
cat > attach.sql <<SQL
INSTALL ducklake; LOAD ducklake;
INSTALL postgres;  LOAD postgres;
INSTALL httpfs;    LOAD httpfs;
INSTALL iceberg;   LOAD iceberg;
CREATE OR REPLACE SECRET s3sec (TYPE s3, PROVIDER credential_chain, REGION '$REGION');
ATTACH 'ducklake:postgres:dbname=ducklake_catalog host=127.0.0.1 user=dl password=dl' AS dl (DATA_PATH 's3://$BUCKET/ducklake/');
ATTACH '$TBARN' AS s3t (TYPE iceberg, ENDPOINT_TYPE s3_tables);
SQL

for GRP in dl.bench s3t.bench; do
  sed "s|__SCHEMA__|$GRP|g" queries.sql > q_${GRP//./_}.sql
  for R in 1 2 3; do
    echo "########## GROUP=$GRP ROUND=$R ##########"
    cat attach.sql q_${GRP//./_}.sql | duckdb :memory: 2>&1 | grep -E "Run Time|########"
  done
done
