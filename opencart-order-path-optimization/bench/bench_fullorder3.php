<?php
// 完整下单量化 v3：对比 txn(仅事务) / batch(total批量) / batch2(product+total都批量)
// 用法: php bench_fullorder3.php <mode> <订单数> <每单商品数>
chdir('/var/www/html'); require_once('config.php');
$mode=$argv[1]??'batch2'; $N=(int)($argv[2]??300); $NP=(int)($argv[3]??5); $P=DB_PREFIX;
$BATCH_TOTAL=($mode==='batch'||$mode==='batch2'); $BATCH_PROD=($mode==='batch2');
$m=new mysqli(DB_HOSTNAME,DB_USERNAME,DB_PASSWORD,DB_DATABASE,(int)DB_PORT);
if($m->connect_errno)die("conn\n"); $m->query("SET autocommit=1");
$ids=[]; $lat=[]; $t0=microtime(true);
for($i=0;$i<$N;$i++){
  $s=microtime(true);
  $m->query("START TRANSACTION");
  $m->query("INSERT INTO `${P}order` SET store_id=0,customer_id=0,firstname='B',email='b".mt_rand()."@x.com',telephone='1',total=".(500*$NP).",order_status_id=0,currency_id=1,currency_code='USD',currency_value=1,date_added=NOW(),date_modified=NOW()");
  $oid=$m->insert_id;
  if($BATCH_PROD){
    $r=[]; for($j=0;$j<$NP;$j++)$r[]="($oid,43,0,'MacBook','P16',1,500,500,100,0)";
    $m->query("INSERT INTO `${P}order_product` (order_id,product_id,master_id,name,model,quantity,price,total,tax,reward) VALUES ".implode(',',$r));
  } else {
    for($j=0;$j<$NP;$j++)$m->query("INSERT INTO `${P}order_product` SET order_id=$oid,product_id=43,master_id=0,name='MacBook',model='P16',quantity=1,price=500,total=500,tax=100,reward=0");
  }
  if($BATCH_TOTAL){
    $m->query("INSERT INTO `${P}order_total` (order_id,extension,code,title,value,sort_order) VALUES ($oid,'total','sub_total','Sub-Total',".(500*$NP).",1),($oid,'total','total','Total',".(500*$NP).",2)");
  } else {
    $m->query("INSERT INTO `${P}order_total` SET order_id=$oid,extension='total',code='sub_total',title='Sub-Total',value=".(500*$NP).",sort_order=1");
    $m->query("INSERT INTO `${P}order_total` SET order_id=$oid,extension='total',code='total',title='Total',value=".(500*$NP).",sort_order=2");
  }
  $m->query("COMMIT");
  // addHistory 部分(与前一致，此处省略读，只算写路径差异)
  $m->query("START TRANSACTION");
  $m->query("UPDATE `${P}product` SET quantity=(quantity-$NP) WHERE product_id=43 AND subtract='1'");
  $m->query("UPDATE `${P}order` SET order_status_id=1,date_modified=NOW() WHERE order_id=$oid");
  $m->query("INSERT INTO `${P}order_history` SET order_id=$oid,order_status_id=1,notify=0,comment='',date_added=NOW()");
  $m->query("COMMIT");
  $lat[]=(microtime(true)-$s)*1000; $ids[]=$oid;
}
$dur=microtime(true)-$t0;
if($ids){$in=implode(',',array_map('intval',$ids));
  foreach(['order','order_product','order_total','order_history']as$t)$m->query("DELETE FROM `${P}${t}` WHERE order_id IN ($in)");
  $m->query("UPDATE `${P}product` SET quantity=quantity+".($N*$NP)." WHERE product_id=43");}
sort($lat); $p95=$lat[(int)($N*0.95)];
printf("mode=%-7s np=%-2d | TPS=%.1f | 每单 avg=%.2fms P95=%.2fms\n",$mode,$NP,$N/$dur,($dur/$N)*1000,$p95);
