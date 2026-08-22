<?php
// 压测端点：通过 HTTP 触发真实的 addOrder + addHistory（改造后代码）
// 放在 web 根，压测机 curl 打它。每次请求下 1 单（含 NP 个商品），返回 JSON。
// 用完删除。仅用于内部压测。
chdir(__DIR__);
require_once('config.php');
require_once(DIR_SYSTEM.'startup.php');
$al=new \Opencart\System\Engine\Autoloader();
$al->register('Opencart\\Catalog',DIR_APPLICATION);
$al->register('Opencart\\System',DIR_SYSTEM);
$al->register('Opencart\\Extension',DIR_EXTENSION);
$reg=new \Opencart\System\Engine\Registry();
$reg->set('db',new \Opencart\System\Library\DB(DB_DRIVER,DB_HOSTNAME,DB_USERNAME,DB_PASSWORD,DB_DATABASE,(int)DB_PORT));
$cfg=new \Opencart\System\Engine\Config();
$cfg->set('application','Catalog');            // Factory 需要
$cfg->set('config_language_id',1);
$reg->set('config',$cfg);
$reg->set('cache',new \Opencart\System\Library\Cache(CACHE_ENGINE,3600));
$reg->set('event',new \Opencart\System\Engine\Event($reg));
$ld=new \Opencart\System\Engine\Loader($reg); $reg->set('load',$ld);
$reg->set('factory',new \Opencart\System\Engine\Factory($reg));

$NP=isset($_GET['np'])?(int)$_GET['np']:3;

$ld->model('checkout/order');
$model=$reg->get('model_checkout_order');

$products=[]; $totals=[];
for($i=0;$i<$NP;$i++)$products[]=['product_id'=>43,'master_id'=>0,'name'=>'MacBook','model'=>'P16','quantity'=>1,'price'=>500,'total'=>500,'tax'=>100,'reward'=>0,'subscription'=>[],'option'=>[]];
$totals[]=['extension'=>'total','code'=>'sub_total','title'=>'Sub-Total','value'=>500*$NP,'sort_order'=>1];
$totals[]=['extension'=>'total','code'=>'total','title'=>'Total','value'=>500*$NP,'sort_order'=>2];

$od=['invoice_prefix'=>'LT-','subscription_id'=>0,'store_id'=>0,'store_name'=>'S','store_url'=>'http://x/','customer_id'=>0,'customer_group_id'=>1,'firstname'=>'L','lastname'=>'T','email'=>'lt'.mt_rand().'@x.com','telephone'=>'1','custom_field'=>[],'payment_address_id'=>0,'payment_firstname'=>'L','payment_lastname'=>'T','payment_company'=>'','payment_address_1'=>'1','payment_address_2'=>'','payment_city'=>'NY','payment_postcode'=>'10001','payment_country'=>'US','payment_country_id'=>223,'payment_zone'=>'NY','payment_zone_id'=>3624,'payment_address_format'=>'','payment_custom_field'=>[],'payment_method'=>['name'=>'COD','code'=>'cod.cod'],'shipping_address_id'=>0,'shipping_firstname'=>'L','shipping_lastname'=>'T','shipping_company'=>'','shipping_address_1'=>'1','shipping_address_2'=>'','shipping_city'=>'NY','shipping_postcode'=>'10001','shipping_country'=>'US','shipping_country_id'=>223,'shipping_zone'=>'NY','shipping_zone_id'=>3624,'shipping_address_format'=>'','shipping_custom_field'=>[],'shipping_method'=>['name'=>'Flat','code'=>'flat.flat'],'comment'=>'','total'=>500*$NP,'affiliate_id'=>0,'commission'=>0,'marketing_id'=>0,'tracking'=>'','language_id'=>1,'language_code'=>'en-gb','currency_id'=>1,'currency_code'=>'USD','currency_value'=>1.0,'ip'=>'127.0.0.1','forwarded_ip'=>'','user_agent'=>'lt','accept_language'=>'en','products'=>$products,'totals'=>$totals];

try {
  $oid=$model->addOrder($od);
  $model->addHistory($oid,1);   // 触发扣库存+order_history
  // 立即清理，避免表膨胀 + 恢复库存
  $db=$reg->get('db'); $P=DB_PREFIX;
  foreach(['order','order_product','order_total','order_option','order_history']as$t)$db->query("DELETE FROM `${P}${t}` WHERE order_id=".(int)$oid);
  $db->query("UPDATE `${P}product` SET quantity=quantity+$NP WHERE product_id=43 AND subtract='1'");
  header('Content-Type: application/json');
  echo json_encode(['success'=>true,'order_id'=>$oid]);
} catch (\Throwable $e) {
  http_response_code(500);
  echo json_encode(['error'=>$e->getMessage()]);
}
