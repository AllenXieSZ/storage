<?php
// 压测端点 v2：用持久连接(pconnect) + 直接 mysqli，隔离"每请求建连接"开销
// 走真实改造后 SQL 序列(addOrder 批量 + addHistory 精简),但用持久连接
// ?np=商品数
$NP=isset($_GET['np'])?(int)$_GET['np']:3;
require_once(__DIR__.'/config.php');
$P=DB_PREFIX;
// 持久连接: host 前加 p:
$m=mysqli_connect('p:'.DB_HOSTNAME, DB_USERNAME, DB_PASSWORD, DB_DATABASE, (int)DB_PORT);
if(!$m){ http_response_code(500); echo json_encode(['error'=>mysqli_connect_error()]); exit; }

try {
  // ===== addOrder (事务 + 批量) =====
  $m->query("START TRANSACTION");
  $m->query("INSERT INTO `${P}order` SET store_id=0,customer_id=0,firstname='L',email='l".mt_rand()."@x.com',telephone='1',total=".(500*$NP).",order_status_id=0,currency_id=1,currency_code='USD',currency_value=1,date_added=NOW(),date_modified=NOW()");
  $oid=$m->insert_id;
  $r=[]; for($j=0;$j<$NP;$j++)$r[]="($oid,43,0,'MacBook','P16',1,500,500,100,0)";
  $m->query("INSERT INTO `${P}order_product` (order_id,product_id,master_id,name,model,quantity,price,total,tax,reward) VALUES ".implode(',',$r));
  $m->query("INSERT INTO `${P}order_total` (order_id,extension,code,title,value,sort_order) VALUES ($oid,'total','sub_total','Sub-Total',".(500*$NP).",1),($oid,'total','total','Total',".(500*$NP).",2)");
  $m->query("COMMIT");

  // ===== addHistory (精简: 合并读 + 事务) =====
  $m->query("START TRANSACTION");
  // 原本 5 次分散 SELECT，这里只保留必要的 products(扣库存要)。合并成一次读
  $pr=$m->query("SELECT product_id,quantity FROM `${P}order_product` WHERE order_id=$oid");
  $qtyByPid=[]; while($row=$pr->fetch_assoc()){ $pid=(int)$row['product_id']; $qtyByPid[$pid]=($qtyByPid[$pid]??0)+(int)$row['quantity']; } $pr->free();
  // 合并扣库存: 每个不同 product 一条(这里都是43，合并为一条)
  foreach($qtyByPid as $pid=>$q){
    $m->query("UPDATE `${P}product` SET quantity=(quantity-$q) WHERE product_id=$pid AND subtract='1'");
  }
  $m->query("UPDATE `${P}order` SET order_status_id=1,date_modified=NOW() WHERE order_id=$oid");
  $m->query("INSERT INTO `${P}order_history` SET order_id=$oid,order_status_id=1,notify=0,comment='',date_added=NOW()");
  $m->query("COMMIT");

  // 清理 + 恢复库存
  foreach(['order','order_product','order_total','order_history']as$t)$m->query("DELETE FROM `${P}${t}` WHERE order_id=$oid");
  foreach($qtyByPid as $pid=>$q)$m->query("UPDATE `${P}product` SET quantity=quantity+$q WHERE product_id=$pid AND subtract='1'");

  header('Content-Type: application/json');
  echo json_encode(['success'=>true,'order_id'=>$oid]);
} catch (\Throwable $e) {
  http_response_code(500); echo json_encode(['error'=>$e->getMessage()]);
}
