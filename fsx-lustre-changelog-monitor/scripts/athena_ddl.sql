CREATE EXTERNAL TABLE IF NOT EXISTS lustre_audit.changelog (
  seq bigint, type string, type_code string, `time` string, flags string, collector string,
  target_fid string, parent_fid string, source_fid string, source_parent_fid string,
  uid int, gid int, client_nid string, client_ip string,
  name string, path string, old_path string )
PARTITIONED BY (mdt string, dt string)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://<BUCKET>/lustre-changelog/'
TBLPROPERTIES (
  'projection.enabled'='true',
  'projection.mdt.type'='injected',
  'projection.dt.type'='date', 'projection.dt.format'='yyyy-MM-dd', 'projection.dt.range'='2026-01-01,NOW',
  'storage.location.template'='s3://<BUCKET>/lustre-changelog/mdt=${mdt}/dt=${dt}/')
