<?php
// addOrder 写路径量化对比：autocommit(改造前) vs 单事务(改造后)
// 忠实复现 addOrder 的 SQL 序列：1 x INSERT order + NP x INSERT order_product + 2 x INSERT order_total
// 用法: php bench_writepath.php <mode:auto|txn> <订单数> <每单商品数>
chdir('/var/www/html');
require_once('config.php');

$mode = $argv[1] ?? 'auto';   // auto | txn
$N    = (int)($argv[2] ?? 500);
$NP   = (int)($argv[3] ?? 3);
$P    = DB_PREFIX;

$m = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int)DB_PORT);
if ($m->connect_errno) { die("conn fail: ".$m->connect_error."\n"); }
$m->query("SET autocommit=1");   // OpenCart 默认

$order_sql = function($m,$P){
  return "INSERT INTO `${P}order` SET `store_id`=0,`customer_id`=0,`firstname`='B',`lastname`='X',`email`='b".mt_rand()."@x.com',`telephone`='1',`total`=".(500).",`order_status_id`=0,`currency_id`=1,`currency_code`='USD',`currency_value`=1,`date_added`=NOW(),`date_modified`=NOW()";
};

$ids = [];
$lat = [];   // 每单耗时(ms)
$t0 = microtime(true);
for ($i=0;$i<$N;$i++) {
  $s = microtime(true);
  if ($mode === 'txn') $m->query("START TRANSACTION");
  $m->query($order_sql($m,$P));
  $oid = $m->insert_id;
  for ($j=0;$j<$NP;$j++) {
    $m->query("INSERT INTO `${P}order_product` SET `order_id`=$oid,`product_id`=43,`name`='MacBook',`model`='P16',`quantity`=1,`price`=500,`total`=500,`tax`=100,`reward`=0");
  }
  $m->query("INSERT INTO `${P}order_total` SET `order_id`=$oid,`extension`='total',`code`='sub_total',`title`='Sub-Total',`value`=".(500*$NP).",`sort_order`=1");
  $m->query("INSERT INTO `${P}order_total` SET `order_id`=$oid,`extension`='total',`code`='total',`title`='Total',`value`=".(500*$NP).",`sort_order`=2");
  if ($mode === 'txn') $m->query("COMMIT");
  $lat[] = (microtime(true)-$s)*1000;
  $ids[] = $oid;
}
$dur = microtime(true)-$t0;

// 清理
if ($ids) {
  $in = implode(',', array_map('intval',$ids));
  $m->query("DELETE FROM `${P}order` WHERE order_id IN ($in)");
  $m->query("DELETE FROM `${P}order_product` WHERE order_id IN ($in)");
  $m->query("DELETE FROM `${P}order_total` WHERE order_id IN ($in)");
}

sort($lat);
$p50 = $lat[(int)($N*0.5)];
$p95 = $lat[(int)($N*0.95)];
$p99 = $lat[min((int)($N*0.99),$N-1)];
printf("mode=%-4s orders=%d np=%d writes/order=%d | dur=%.3fs TPS=%.1f | 每单 avg=%.2fms P50=%.2f P95=%.2f P99=%.2fms\n",
  $mode, $N, $NP, 1+$NP+2, $dur, $N/$dur, ($dur/$N)*1000, $p50, $p95, $p99);
