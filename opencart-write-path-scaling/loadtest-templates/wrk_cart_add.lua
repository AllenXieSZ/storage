-- wrk 写路径压测: cart.add (加入购物车, POST) —— 冲 5000 TPS 的主力脚本
-- 用法: wrk -t12 -c600 -d300s -s wrk_cart_add.lua http://TARGET
-- 说明: OpenCart4 加购接口 = index.php?route=checkout/cart.add
--       POST body: product_id=<pid>&quantity=1
--       CloudFront 不缓存 POST, 会全透传到 ALB→后端, 所以是真实写压力。

local product_ids = {}
for i = 20, 329 do product_ids[#product_ids+1] = i end

math.randomseed(os.time() + (tonumber(tostring({}):match("0x(%x+)"), 16) or 0))

wrk.method = "POST"
wrk.headers["Content-Type"] = "application/x-www-form-urlencoded"

request = function()
  local pid = product_ids[math.random(#product_ids)]
  local body = "product_id=" .. pid .. "&quantity=1"
  return wrk.format("POST", "/index.php?route=checkout/cart.add&language=en-gb", nil, body)
end

local ok2xx, errs = 0, 0
response = function(status, headers, body)
  if status >= 200 and status < 400 then ok2xx = ok2xx + 1 else errs = errs + 1 end
end

done = function(summary, latency, requests)
  io.write(string.format(
    "\n[cart.add] 请求=%d  2xx/3xx=%d  错误(>=400/5xx)=%d\n" ..
    "           TPS(近似)=%.1f  P50=%.1fms P95=%.1fms P99=%.1fms\n",
    summary.requests, ok2xx, errs,
    summary.requests / (summary.duration/1e6),
    latency:percentile(50)/1000, latency:percentile(95)/1000, latency:percentile(99)/1000))
end
