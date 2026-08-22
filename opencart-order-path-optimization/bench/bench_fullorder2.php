<?php
// 完整下单写路径量化 v2：对比 auto / txn / batch(txn+多值INSERT)
// batch 模式：order_product 和 order_total 各用一条多值 INSERT 替代循环单条
// 用法: php bench_fullorder2.php <mode:auto|txn|batch> <订单数> <每单商品数>
chdir('/var/www/html');
require_once('config.php');

$mode = $argv[1] ?? 'auto';
$N    = (int)($argv[2] ?? 400);
$NP   = (int)($argv[3] ?? 3);
$P    = DB_PREFIX;
$TXN  = ($mode==='txn' || $mode==='batch');
$BATCH= ($mode==='batch');

$m = new mysqli(DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int)DB_PORT);
if ($m->connect_errno) { die("conn fail: ".$m->connect_error."\n"); }
$m->query("SET autocommit=1");

$ids = [];
$lat = [];
$t0 = microtime(true);
for ($i=0;$i<$N;$i++) {
  $s = microtime(true);

  // ===== addOrder =====
  if ($TXN) $m->query("START TRANSACTION");
  $m->query("INSERT INTO `${P}order` SET `store_id`=0,`customer_id`=0,`firstname`='B',`lastname`='X',`email`='b".mt_rand()."@x.com',`telephone`='1',`total`=".(500*$NP).",`order_status_id`=0,`currency_id`=1,`currency_code`='USD',`currency_value`=1,`date_added`=NOW(),`date_modified`=NOW()");
  $oid = $m->insert_id;

  if ($BATCH) {
    // 一条多值 INSERT 写入所有 order_product
    $vals=[];
    for ($j=0;$j<$NP;$j++) $vals[]="($oid,43,'MacBook','P16',1,500,500,100,0)";
    $m->query("INSERT INTO `${P}order_product` (order_id,product_id,name,model,quantity,price,total,tax,reward) VALUES ".implode(',',$vals));
    // 一条多值 INSERT 写入所有 order_total
    $m->query("INSERT INTO `${P}order_total` (order_id,extension,code,title,value,sort_order) VALUES ($oid,'total','sub_total','Sub-Total',".(500*$NP).",1),($oid,'total','total','Total',".(500*$NP).",2)");
  } else {
    for ($j=0;$j<$NP;$j++)
      $m->query("INSERT INTO `${P}order_product` SET `order_id`=$oid,`product_id`=43,`name`='MacBook',`model`='P16',`quantity`=1,`price`=500,`total`=500,`tax`=100,`reward`=0");
    $m->query("INSERT INTO `${P}order_total` SET `order_id`=$oid,`extension`='total',`code`='sub_total',`title`='Sub-Total',`value`=".(500*$NP).",`sort_order`=1");
    $m->query("INSERT INTO `${P}order_total` SET `order_id`=$oid,`extension`='total',`code`='total',`title`='Total',`value`=".(500*$NP).",`sort_order`=2");
  }
  if ($TXN) $m->query("COMMIT");

  // ===== addHistory (0->1) =====
  if ($TXN) $m->query("START TRANSACTION");
  $m->query("SELECT * FROM `${P}order` WHERE order_id=$oid")->free();
  $m->query("SELECT * FROM `${P}customer` WHERE customer_id=0 LIMIT 1");
  $pr = $m->query("SELECT * FROM `${P}order_product` WHERE order_id=$oid"); $prods=[]; while($r=$pr->fetch_assoc())$prods[]=$r; $pr->free();
  $m->query("SELECT * FROM `${P}order_subscription` WHERE order_id=$oid")->free();
  $m->query("SELECT * FROM `${P}order_total` WHERE order_id=$oid")->free();
  if ($BATCH) {
    // 合并扣库存：一条 UPDATE 扣所有商品（这里都是 product 43，合并按数量）
    $m->query("UPDATE `${P}product` SET `quantity`=(`quantity`-".$NP.") WHERE `product_id`=43 AND `subtract`='1'");
    // getOptions 合并成一次查询（IN 所有 order_product_id）
    if ($prods){ $opids=implode(',',array_map(fn($p)=>(int)$p['order_product_id'],$prods)); $m->query("SELECT * FROM `${P}order_option` WHERE order_id=$oid AND order_product_id IN ($opids)")->free(); }
  } else {
    foreach ($prods as $pp) {
      $m->query("UPDATE `${P}product` SET `quantity`=(`quantity`-1) WHERE `product_id`=".(int)$pp['product_id']." AND `subtract`='1'");
      $m->query("SELECT * FROM `${P}order_option` WHERE order_id=$oid AND order_product_id=".(int)$pp['order_product_id'])->free();
    }
  }
  $m->query("UPDATE `${P}order` SET `order_status_id`=1,`date_modified`=NOW() WHERE order_id=$oid");
  $m->query("INSERT INTO `${P}order_history` SET `order_id`=$oid,`order_status_id`=1,`notify`=0,`comment`='',`date_added`=NOW()");
  if ($TXN) $m->query("COMMIT");

  $lat[] = (microtime(true)-$s)*1000;
  $ids[] = $oid;
}
$dur = microtime(true)-$t0;

if ($ids) {
  $in = implode(',', array_map('intval',$ids));
  foreach (['order','order_product','order_total','order_history'] as $t)
    $m->query("DELETE FROM `${P}${t}` WHERE order_id IN ($in)");
  $m->query("UPDATE `${P}product` SET `quantity`=`quantity`+".($N*$NP)." WHERE product_id=43");
}

sort($lat);
$p50=$lat[(int)($N*0.5)]; $p95=$lat[(int)($N*0.95)]; $p99=$lat[min((int)($N*0.99),$N-1)];
printf("mode=%-6s orders=%d np=%d | dur=%.3fs TPS=%.1f | 每单 avg=%.2fms P50=%.2f P95=%.2f P99=%.2fms\n",
  $mode,$N,$NP,$dur,$N/$dur,($dur/$N)*1000,$p50,$p95,$p99);
