<?php
// 完整下单写路径量化：addOrder + addHistory 的 SQL 序列，对比 autocommit vs 单事务
// addOrder: 1 INSERT order + NP INSERT product + 2 INSERT total
// addHistory(status 0->1 处理中): getOrder(1 SELECT) + getCustomer(1) + getProducts(1) + getSubscriptions(1) + getTotals(1)
//            + 每商品扣库存 UPDATE product(1) + getOptions(1 SELECT) + editOrderStatusId(1 UPDATE) + INSERT order_history(1)
// 用法: php bench_fullorder.php <mode:auto|txn> <订单数> <每单商品数>
chdir('/var/www/html');
require_once('config.php');

$mode = $argv[1] ?? 'auto';
$N    = (int)($argv[2] ?? 500);
$NP   = (int)($argv[3] ?? 3);
$P    = DB_PREFIX;

$m = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int)DB_PORT);
if ($m->connect_errno) { die("conn fail: ".$m->connect_error."\n"); }
$m->query("SET autocommit=1");

$ids = [];
$lat = [];
$t0 = microtime(true);
for ($i=0;$i<$N;$i++) {
  $s = microtime(true);

  // ===== addOrder =====
  if ($mode==='txn') $m->query("START TRANSACTION");
  $m->query("INSERT INTO `${P}order` SET `store_id`=0,`customer_id`=0,`firstname`='B',`lastname`='X',`email`='b".mt_rand()."@x.com',`telephone`='1',`total`=".(500*$NP).",`order_status_id`=0,`currency_id`=1,`currency_code`='USD',`currency_value`=1,`date_added`=NOW(),`date_modified`=NOW()");
  $oid = $m->insert_id;
  for ($j=0;$j<$NP;$j++)
    $m->query("INSERT INTO `${P}order_product` SET `order_id`=$oid,`product_id`=43,`name`='MacBook',`model`='P16',`quantity`=1,`price`=500,`total`=500,`tax`=100,`reward`=0");
  $m->query("INSERT INTO `${P}order_total` SET `order_id`=$oid,`extension`='total',`code`='sub_total',`title`='Sub-Total',`value`=".(500*$NP).",`sort_order`=1");
  $m->query("INSERT INTO `${P}order_total` SET `order_id`=$oid,`extension`='total',`code`='total',`title`='Total',`value`=".(500*$NP).",`sort_order`=2");
  if ($mode==='txn') $m->query("COMMIT");

  // ===== addHistory (0->1) =====
  if ($mode==='txn') $m->query("START TRANSACTION");
  // getOrder / getCustomer / getProducts / getSubscriptions / getTotals (5 SELECT)
  $m->query("SELECT * FROM `${P}order` WHERE order_id=$oid")->free();
  $m->query("SELECT * FROM `${P}customer` WHERE customer_id=0 LIMIT 1");
  $pr = $m->query("SELECT * FROM `${P}order_product` WHERE order_id=$oid"); $prods=[]; while($r=$pr->fetch_assoc())$prods[]=$r; $pr->free();
  $m->query("SELECT * FROM `${P}order_subscription` WHERE order_id=$oid")->free();
  $m->query("SELECT * FROM `${P}order_total` WHERE order_id=$oid")->free();
  // 扣库存 + getOptions
  foreach ($prods as $pp) {
    $m->query("UPDATE `${P}product` SET `quantity`=(`quantity`-1) WHERE `product_id`=".(int)$pp['product_id']." AND `subtract`='1'");
    $m->query("SELECT * FROM `${P}order_option` WHERE order_id=$oid AND order_product_id=".(int)$pp['order_product_id'])->free();
  }
  // editOrderStatusId + INSERT order_history
  $m->query("UPDATE `${P}order` SET `order_status_id`=1,`date_modified`=NOW() WHERE order_id=$oid");
  $m->query("INSERT INTO `${P}order_history` SET `order_id`=$oid,`order_status_id`=1,`notify`=0,`comment`='',`date_added`=NOW()");
  if ($mode==='txn') $m->query("COMMIT");

  $lat[] = (microtime(true)-$s)*1000;
  $ids[] = $oid;
}
$dur = microtime(true)-$t0;

// 清理
if ($ids) {
  $in = implode(',', array_map('intval',$ids));
  foreach (['order','order_product','order_total','order_history'] as $t)
    $m->query("DELETE FROM `${P}${t}` WHERE order_id IN ($in)");
  // 恢复被扣的库存
  $m->query("UPDATE `${P}product` SET `quantity`=`quantity`+".($N*$NP)." WHERE product_id=43");
}

sort($lat);
$p50=$lat[(int)($N*0.5)]; $p95=$lat[(int)($N*0.95)]; $p99=$lat[min((int)($N*0.99),$N-1)];
printf("mode=%-4s orders=%d np=%d | dur=%.3fs TPS=%.1f | 每单 avg=%.2fms P50=%.2f P95=%.2f P99=%.2fms\n",
  $mode,$N,$NP,$dur,$N/$dur,($dur/$N)*1000,$p50,$p95,$p99);
