# OpenCart 4 PayPal 沙箱支付扩展（自研，演示用）

OpenCart 4.1.0.4 **不自带** PayPal 扩展（官方仅 cod/cheque/bank_transfer/free_checkout）。本扩展用 **PayPal Orders API v2** 实现完整在线支付流程，用于演示（sandbox）。

> ⚠️ 凭证（client_id/secret）不在代码里，存 OpenCart setting（DB）。本仓库仅代码，无任何凭证。

## 支付流程
1. 结账页选 PayPal → 点 Confirm Order → 触发 `paypalsb.confirm`
2. `confirm()`：拿 access token → 创建 PayPal order（CAPTURE intent）→ 返回 approve URL
3. 前端 JS 跳转到 `sandbox.paypal.com` → 用户用沙箱买家账号登录支付
4. PayPal 回调 `paypalsb.callback` → capture 付款 → 订单标记已处理 → 跳成功页

## 文件（OpenCart 4 扩展结构）
- `catalog_controller_paypalsb.php` → `extension/opencart/catalog/controller/payment/paypalsb.php`（核心：token/confirm/callback）
- 另需 catalog model(getMethods)/language/view(twig) + admin controller/language/view（配置页）
- DB：`oc_extension` 注册 (opencart/payment/paypalsb) + `oc_setting` 存 client_id/secret/status/order_status_id

## 关键坑（血泪）
1. **OpenCart 4 支付确认是两段式**：主 Confirm Order → 加载支付方式 index() 视图（含二次确认按钮）→ 再点才真正 confirm。view 用标准 jQuery（对齐 cod.twig），别用原生 fetch。
2. **`error_log`/敏感文件写位置**：调试日志写明确文件。
3. **⚠️ 删 curl_close 的坑**：`$r = json_decode(curl_exec($ch), true); curl_close($ch);` 若写在同一行，用 `sed '/curl_close/d'` 会把整行连 curl_exec 结果赋值一起删掉 → `$r` undefined → token/订单/capture 全失败。**PHP 8.5 curl_close 已废弃无副作用，可直接不写，但删除时要精确替换而非整行删**。
4. **setting 存 store_id=0 + serialized=0**，与 cod 一致；catalog startup 会 getSettings(0) 加载，`$this->config->get('payment_paypalsb_xxx')` 可读。
5. MetadataConfiguration 无关；OpenCart 前台 config 加载 store 0 全部 setting。

## 生产化提醒
- 演示用 sandbox（`api-m.sandbox.paypal.com`）。真实收款：换 `api-m.paypal.com` + 生产 client_id/secret + PayPal Business 账户签约过审。
- 后端需能出公网连 PayPal API（若 web server 在私有子网去了 NAT，PayPal 支付会失败）。
