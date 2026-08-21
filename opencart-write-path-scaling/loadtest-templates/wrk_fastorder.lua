-- wrk 一键下单接口压测: fastorder (自定义快速下单, POST) —— 端到端下单 TPS
-- 用法: wrk -t12 -c600 -d300s -s wrk_fastorder.lua http://TARGET
-- 说明: fastorder 是自定义的一键下单 controller
--        (catalog/controller/checkout/fastorder.php), 直接创建订单返回 {success, order_id}。
--        用于测"真实下单"的端到端 TPS(比 cart.add 更重, 会写 oc_order 等表)。
--        product_id 需选无必填选项的商品, 否则报 "option required"。

local product_ids = {}
-- 只放确认无必填选项的商品 id(按你的数据调整); 这里用一段连续区间做示例
for i = 43, 300 do product_ids[#product_ids+1] = i end

math.randomseed(os.time() + (tonumber(tostring({}):match("0x(%x+)"), 16) or 0))

wrk.method = "POST"
wrk.headers["Content-Type"] = "application/x-www-form-urlencoded"

request = function()
  local pid = product_ids[math.random(#product_ids)]
  local body = "product_id=" .. pid .. "&quantity=1"
  return wrk.format("POST", "/index.php?route=checkout/fastorder&language=en-gb", nil, body)
end

local success, fail = 0, 0
response = function(status, headers, body)
  -- fastorder 返回 JSON {"success":true,"order_id":N} 或 {"error":...}
  if status < 400 and body and body:find('"success"') and body:find('true') then
    success = success + 1
  else
    fail = fail + 1
  end
end

done = function(summary, latency, requests)
  io.write(string.format(
    "\n[fastorder] 提交=%d  成功单=%d  失败=%d\n" ..
    "            下单TPS(近似)=%.1f  P50=%.1fms P95=%.1fms P99=%.1fms\n",
    summary.requests, success, fail,
    summary.requests / (summary.duration/1e6),
    latency:percentile(50)/1000, latency:percentile(95)/1000, latency:percentile(99)/1000))
end
