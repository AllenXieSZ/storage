-- wrk 读路径压测: 随机打 首页 / 分类页 / 商品页 (GET)
-- 用法: wrk -t8 -c400 -d60s -s wrk_browse.lua http://TARGET
-- 说明: OpenCart4 路由用 index.php?route=... ; 商品/分类 id 池按你灌的数据调整

local product_ids = {}
for i = 20, 329 do product_ids[#product_ids+1] = i end
local category_paths = {20,18,33,28,34,25,27,26,29,57,60}

math.randomseed(os.time() + (tonumber(tostring({}):match("0x(%x+)"), 16) or 0))

request = function()
  local r = math.random()
  local path
  if r < 0.34 then
    path = "/"
  elseif r < 0.67 then
    local c = category_paths[math.random(#category_paths)]
    path = "/index.php?route=product/category&language=en-gb&path=" .. c
  else
    local p = product_ids[math.random(#product_ids)]
    path = "/index.php?route=product/product&language=en-gb&product_id=" .. p
  end
  return wrk.format("GET", path)
end

-- 统计非 2xx/3xx 响应
local errs = 0
response = function(status)
  if status >= 400 then errs = errs + 1 end
end

done = function(summary, latency, requests)
  io.write(string.format("\n[browse] 请求总数=%d  错误(>=400)=%d  P50=%.1fms P90=%.1fms P99=%.1fms\n",
    summary.requests, errs,
    latency:percentile(50)/1000, latency:percentile(90)/1000, latency:percentile(99)/1000))
end
