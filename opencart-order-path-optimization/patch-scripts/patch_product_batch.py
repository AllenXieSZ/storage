#!/usr/bin/env python3
# 把 addOrder 里的 products 循环改成批量 INSERT + option 关联回填
import sys
f = "/var/www/html/catalog/model/checkout/order.php"
s = open(f).read()

if "batch order_product" in s:
    print("already patched"); sys.exit(0)

old = """		// Products
		if (!empty($data['products'])) {
			foreach ($data['products'] as $product) {
				$this->model_checkout_order->addProduct($order_id, $product);
			}
		}"""

# 批量方案：
# 1) 一条多值 INSERT 写所有 order_product，拿首行 id
# 2) 依据 innodb_autoinc_lock_mode 下单条多值 INSERT 内部 id 连续，order_product_id = firstId + index
# 3) 收集所有 option 一条多值 INSERT；subscription 少见，逐条调用（保留 addSubscription 逻辑）
new = """		// Products (batch order_product INSERT + option 关联回填)
		if (!empty($data['products'])) {
			$prod_rows = [];
			foreach ($data['products'] as $product) {
				$prod_rows[] = "('" . (int)$order_id . "', '" . (int)$product['product_id'] . "', '" . (int)$product['master_id'] . "', '" . $this->db->escape($product['name']) . "', '" . $this->db->escape($product['model']) . "', '" . (int)$product['quantity'] . "', '" . (float)$product['price'] . "', '" . (float)$product['total'] . "', '" . (float)$product['tax'] . "', '" . (int)$product['reward'] . "')";
			}

			$this->db->query("INSERT INTO `" . DB_PREFIX . "order_product` (`order_id`, `product_id`, `master_id`, `name`, `model`, `quantity`, `price`, `total`, `tax`, `reward`) VALUES " . implode(', ', $prod_rows));

			// 单条多值 INSERT 内部自增 id 连续（已实测确认），首行 id + 序号推算每行 order_product_id
			$first_order_product_id = $this->db->getLastId();

			// 收集 option 批量写；subscription 逐条（少见）
			$option_rows = [];

			$idx = 0;
			foreach ($data['products'] as $product) {
				$order_product_id = $first_order_product_id + $idx;

				if (!empty($product['option'])) {
					foreach ($product['option'] as $option) {
						$option_rows[] = "('" . (int)$order_id . "', '" . (int)$order_product_id . "', '" . (int)$option['product_option_id'] . "', '" . (int)$option['product_option_value_id'] . "', '" . $this->db->escape($option['name']) . "', '" . $this->db->escape($option['value']) . "', '" . $this->db->escape($option['type']) . "')";
					}
				}

				if (!empty($product['subscription'])) {
					$this->model_checkout_order->addSubscription($order_id, $order_product_id, $product['subscription'] + ['quantity' => $product['quantity']]);
				}

				$idx++;
			}

			if ($option_rows) {
				$this->db->query("INSERT INTO `" . DB_PREFIX . "order_option` (`order_id`, `order_product_id`, `product_option_id`, `product_option_value_id`, `name`, `value`, `type`) VALUES " . implode(', ', $option_rows));
			}
		}"""

if old in s:
    s = s.replace(old, new)
    open(f,"w").write(s)
    print("patched: batch order_product")
else:
    print("WARN: products loop pattern not found")
