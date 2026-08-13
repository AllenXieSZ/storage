#!/usr/bin/env python3
"""Generate an independent Grafana dashboard for Mountpoint-S3 OTLP metrics.

Metrics come from mount-s3 --otlp-endpoint -> Prometheus v3 (:9091, native histograms)
Fully independent of the legacy EBS `node_ebs_*` dashboard (id=43) on Grafana :3000.

Metric names (verified live via /api/v1/label/__name__/values on 2026-07-27):
  fuse_io_size_bytes                          (native histogram)
  fuse_request_errors_total                   (counter)
  fuse_request_latency_microseconds           (native histogram)
  process_memory_usage_bytes                  (gauge)
  s3_request_count_total                      (counter)
  s3_request_errors_total                     (counter)
  s3_request_first_byte_latency_microseconds  (native histogram)
  s3_request_total_latency_microseconds       (native histogram)
  experimental_fuse_idle_threads              (native histogram)
  experimental_fuse_total_threads_ratio       (gauge)
"""
import json

DS = {"type": "prometheus", "uid": "${DS_PROM_MP}"}
panels = []
_id = [0]


def nid():
    _id[0] += 1
    return _id[0]


def target(expr, legend, fmt="time_series"):
    # refId is assigned per-panel later by _fix_refids(); duplicates cause Grafana
    # to drop all but one query -> panel shows "No data".
    return {
        "datasource": DS,
        "editorMode": "code",
        "expr": expr,
        "legendFormat": legend,
        "range": True,
        "refId": None,
        "format": fmt,
    }


def _fix_refids():
    """Assign unique sequential refIds (A, B, C...) within each panel."""
    for p in panels:
        for i, t in enumerate(p.get("targets", []) or []):
            t["refId"] = chr(65 + i) if i < 26 else "Q%d" % i


def row(title, y):
    panels.append({
        "id": nid(), "type": "row", "title": title, "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": [],
    })


def timeseries(title, x, y, w, h, targets, unit="", desc="", stack=False,
               log=0, hide_legends=None, thresholds=None):
    """log: 0=linear, 2 or 10 = logarithmic base. Needed when series span many
    orders of magnitude (measured: getattr 29us vs flush 2,133,810us = 5 decades;
    on a linear axis every fast op collapses onto the zero line).
    hide_legends: legendFormat values hidden from the plot (kept in legend table).
    thresholds: [(value, color)] drawn as dashed lines."""
    custom = {
        "drawStyle": "line", "lineWidth": 2, "fillOpacity": 8,
        "showPoints": "never", "spanNulls": True,
        "stacking": {"mode": "normal" if stack else "none", "group": "A"},
    }
    if log:
        custom["scaleDistribution"] = {"type": "log", "log": log}
    defaults = {"unit": unit, "custom": custom, "color": {"mode": "palette-classic"}}
    overrides = []
    for lg in (hide_legends or []):
        overrides.append({
            "matcher": {"id": "byName", "options": lg},
            "properties": [{"id": "custom.hideFrom",
                            "value": {"legend": False, "tooltip": False, "viz": True}}],
        })
    if thresholds:
        defaults["thresholds"] = {"mode": "absolute", "steps":
            [{"color": "green", "value": None}] +
            [{"color": c, "value": v} for v, c in thresholds]}
        custom["thresholdsStyle"] = {"mode": "dashed"}
    panels.append({
        "id": nid(), "type": "timeseries", "title": title, "description": desc,
        "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": overrides},
        "options": {
            "legend": {"displayMode": "table", "placement": "bottom",
                       "calcs": ["mean", "max", "lastNotNull"], "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    })


def heatmap(title, x, y, w, h, expr, unit="µs", desc=""):
    """Native-histogram heatmap: Grafana renders bucket distribution over time."""
    panels.append({
        "id": nid(), "type": "heatmap", "title": title, "description": desc,
        "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [{
            "datasource": DS, "editorMode": "code", "expr": expr,
            "format": "heatmap", "legendFormat": "{{le}}", "range": True, "refId": "A",
        }],
        "options": {
            "calculate": False,
            "cellGap": 1,
            "color": {"mode": "scheme", "scheme": "Turbo", "steps": 64,
                      "reverse": False, "exponent": 0.5, "fill": "dark-orange"},
            "yAxis": {"unit": unit, "axisPlacement": "left", "reverse": False},
            "tooltip": {"mode": "single", "showColorScale": True, "yHistogram": True},
            "legend": {"show": True},
            "exemplars": {"color": "rgba(255,0,255,0.7)"},
            "filterValues": {"le": 1e-9},
            "rowsFrame": {"layout": "auto"},
        },
        "fieldConfig": {"defaults": {"custom": {"hideFrom":
                        {"tooltip": False, "viz": False, "legend": False}}}, "overrides": []},
    })


def stat(title, x, y, w, h, targets, unit="", desc="", graph=True,
         steps=None, color_mode="value"):
    """steps: [(value, color)] absolute thresholds; first entry should be (None, color)."""
    tsteps = ([{"color": "green", "value": None}] if steps is None
              else [{"color": c, "value": v} for v, c in steps])
    panels.append({
        "id": nid(), "type": "stat", "title": title, "description": desc,
        "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": targets,
        "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "thresholds"},
                        "thresholds": {"mode": "absolute", "steps": tsteps}}, "overrides": []},
        "options": {"graphMode": "area" if graph else "none", "colorMode": color_mode,
                    "textMode": "auto", "justifyMode": "auto",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    })


# ============================================================
# Row 1: Overview
# ------------------------------------------------------------
# Revised 2026-07-27 after a real load test (light 10MB/s vs heavy 550MB/s).
# Findings that forced changes here:
#   * A single "S3 errors/s" stat lumped benign HeadObject 404 (POSIX O_CREAT
#     existence probe) and http_status=-1 (Mountpoint cancelling duplicate
#     lookups, CRT 14347 "Request successfully cancelled") together with real
#     5xx. It read 0.4/s while S3 was in fact 100% healthy -> actively misleading.
#   * "Throughput (FUSE)" showed 64 MB/s while fio measured 437 MB/s at the
#     application layer, because page-cache hits never reach FUSE (6.8x under-report).
# ============================================================
row("Overview", 0)
stat("FUSE ops/s", 0, 1, 4, 4,
     [target("sum(histogram_count(rate(fuse_request_latency_microseconds[$__rate_interval])))", "ops/s")],
     "ops", "Total FUSE request rate (all types). NOTE: read requests are split by the "
            "kernel into ~256KB chunks (measured p50 249KB from 1MiB app reads), so this "
            "does not equal the application's IO operation count.")
stat("S3 API req/s", 4, 1, 4, 4,
     [target("sum(rate(s3_request_count_total[$__rate_interval]))", "req/s")], "reqps",
     "Measured cross-check: 63 req/s UploadPart x 8MiB part = 504 MB/s, matching FUSE "
     "write throughput exactly -> default --write-part-size 8388608 with no retry waste.")
stat("Throughput (FUSE layer only)", 8, 1, 4, 4,
     [target("sum(histogram_sum(rate(fuse_io_size_bytes[$__rate_interval])))", "B/s")],
     "Bps", "!! NOT application throughput. Page-cache hits never reach FUSE, so this "
            "UNDER-REPORTS by a varying factor: measured 6.8x low in a cache-friendly "
            "read-only run (64 MB/s here vs 437 MB/s in fio) and 1.7x low under mixed "
            "read+write (474 MB/s here vs ~787 MB/s app-side). The gap tracks cache hit "
            "rate, so treat it as a floor, never as the capacity-planning number.")
stat("FUSE errors/s (app-visible)", 12, 1, 4, 4,
     [target("sum(rate(fuse_request_errors_total[$__rate_interval]))", "err/s")], "short",
     "HIGHEST-SIGNAL error metric: a non-zero value means the application actually "
     "received an I/O error. Stayed at 0 through the entire 2026-07-27 load test even "
     "while the S3 layer showed transient events (Mountpoint retried them all).",
     steps=[(None, "green"), (0.001, "red")])
stat("S3 real errors/s", 16, 1, 4, 4,
     [target('sum(rate(s3_request_errors_total{http_status!~"404|-1"}[$__rate_interval]))',
             "real err/s")], "short",
     "Excludes http_status 404 and -1, both of which are NORMAL behaviour "
     "(404 = O_CREAT existence probe; -1 = Mountpoint cancelling a duplicate lookup). "
     "Only 5xx / throttling / genuine failures land here.",
     steps=[(None, "green"), (0.001, "red")])
stat("Mountpoint RSS", 20, 1, 4, 4,
     [target("max(process_memory_usage_bytes)", "RSS")], "bytes",
     "Measured growth: 80MB idle -> 617MB write -> 978MB read on a 7.8GB c6i.xlarge "
     "(12x). Reads cost more memory than writes. Watch for OOM on small instances.",
     steps=[(None, "green"), (2147483648, "orange"), (4294967296, "red")])

# Benign-event + bottleneck strip: promoted out of the bottom rows because these
# two views are what actually prevent misdiagnosis (see comments above).
timeseries("S3 benign events by status (404 = O_CREAT probe, -1 = cancelled dup lookup)",
           0, 5, 12, 6, [
    target('sum by (s3_request, http_status) (rate(s3_request_errors_total{http_status=~"404|-1"}[$__rate_interval]))',
           "{{s3_request}} / {{http_status}}"),
], "short",
    "Counted in s3_request_errors_total but NOT failures. Verified with --debug --debug-crt "
    "on 2026-07-27: 149x CRT 14343 (all response status=404) + 19x CRT 14347 "
    "AWS_ERROR_S3_CANCELED 'Request successfully cancelled' (all HeadObject, 0 UploadPart). "
    "All 42,865 UploadPart calls returned 200.")
timeseries("S3 bottleneck indicator — TOTAL p99 / TTFB p99", 12, 5, 12, 6, [
    target("histogram_quantile(0.99, sum by (s3_request) (rate(s3_request_total_latency_microseconds[$__rate_interval])))"
           " / "
           "histogram_quantile(0.99, sum by (s3_request) (rate(s3_request_first_byte_latency_microseconds[$__rate_interval])))",
           "{{s3_request}}"),
], "none",
    "Ratio ~1 => S3/network is the bottleneck. Ratio >> 1 => TTFB is fine but the body "
    "transfer is slow, i.e. LOCAL bandwidth/concurrency limit, NOT S3 being slow. "
    "Measured 2026-07-27: UploadPart 9.8x (TTFB 138ms vs TOTAL 1.34s), GetObject 26.1x. "
    "Without this ratio the natural (wrong) conclusion is 'S3 got slower'.",
    log=2, thresholds=[(8, "orange")])

# ============================================================
# Row 2: FUSE latency — the histogram story
# ============================================================
row("FUSE Request Latency (native histogram)", 11)
heatmap("FUSE latency distribution — heatmap (all requests)", 0, 12, 12, 9,
        "sum(rate(fuse_request_latency_microseconds[$__rate_interval]))",
        "µs", "Native-histogram bucket distribution over time. Bright = where latency "
              "concentrates. Measured under load this is clearly BIMODAL: a dense band at "
              "128us-1ms plus sparse points out past 300ms.")
timeseries("FUSE latency percentiles (all requests)", 12, 12, 12, 9, [
    target("histogram_quantile(0.50, sum(rate(fuse_request_latency_microseconds[$__rate_interval])))", "p50"),
    target("histogram_quantile(0.90, sum(rate(fuse_request_latency_microseconds[$__rate_interval])))", "p90"),
    target("histogram_quantile(0.99, sum(rate(fuse_request_latency_microseconds[$__rate_interval])))", "p99"),
    target("histogram_quantile(0.999, sum(rate(fuse_request_latency_microseconds[$__rate_interval])))", "p99.9"),
    target("histogram_quantile(0.9999, sum(rate(fuse_request_latency_microseconds[$__rate_interval])))", "p99.99"),
    target("histogram_avg(sum(rate(fuse_request_latency_microseconds[$__rate_interval])))", "avg (hidden — misleading)"),
], "µs",
    "True quantiles from exponential histogram buckets. Measured heavy write: "
    "p50 250us / p99 213,634us (855x). Measured mixed read+write: p50 64us / p90 311us / "
    "p99 23,947us / p99.9 390,052us / p99.99 1,226,967us -> p99.99 is 19,231x p50. "
    "The mean is hidden by default: it read 1,670us vs a p50 of 64us (26x inflated by "
    "the tail), i.e. it describes neither the typical nor the worst request.",
    log=2, hide_legends=["avg (hidden — misleading)"])

timeseries("FUSE p99 latency by request type", 0, 21, 12, 8, [
    target("histogram_quantile(0.99, sum by (fuse_request) (rate(fuse_request_latency_microseconds[$__rate_interval])))",
           "{{fuse_request}}"),
], "µs",
    "LOG AXIS is mandatory: measured 11 op types spanning 5 decades in one chart "
    "(releasedir 26us / release 57us / opendir 1,327us / getattr 1,384us / read 13,742us / "
    "mknod 14,116us / write 46,669us / readdirplus 169,685us / open 557,957us / "
    "lookup 616,637us / flush 1,931,987us) -- a 74,307x spread. On a linear axis eight "
    "of these collapse onto the zero line and look perfectly flat.",
    log=10)
timeseries("FUSE time contribution by request type (where wall-clock actually goes)",
           12, 21, 12, 8, [
    target("sum by (fuse_request) (histogram_sum(rate(fuse_request_latency_microseconds[$__rate_interval])))",
           "{{fuse_request}}"),
], "µs",
    "histogram_sum, NOT histogram_count: total microseconds spent per op type. "
    "Added because ops/s is misleading about importance. Measured under mixed load: "
    "read 4,042,068 us/s (66% of time, 2932 ops/s) but flush 673,281 us/s (11% of time "
    "from only 0.5 ops/s = 0.017% of requests). flush is the classic case a "
    "count-weighted average dilutes into invisibility.",
    stack=True)

timeseries("FUSE ops/s by request type", 0, 29, 12, 7, [
    target("sum by (fuse_request) (histogram_count(rate(fuse_request_latency_microseconds[$__rate_interval])))",
           "{{fuse_request}}"),
], "ops",
    "Request COUNT only -- do not infer importance from this. Measured under mixed load: "
    "read 2932 ops/s and write 259 ops/s vs flush 0.5 ops/s, yet flush still burns 11% "
    "of all wall-clock time (0.017% of requests). Always pair with the time-contribution "
    "panel above.",
    stack=True)
heatmap("FUSE read latency — heatmap", 12, 29, 12, 7,
        'sum(rate(fuse_request_latency_microseconds{fuse_request="read"}[$__rate_interval]))', "µs")
heatmap("FUSE write latency — heatmap", 0, 36, 12, 7,
        'sum(rate(fuse_request_latency_microseconds{fuse_request="write"}[$__rate_interval]))', "µs",
        "Measured: write p50 barely moves with load (261us light -> 254us heavy, data is "
        "buffered) while p99 explodes 304us -> 140,680us when the buffer periodically fills.")
heatmap("FUSE flush latency — heatmap (close() waiting on CompleteMultipartUpload)",
        12, 36, 12, 7,
        'sum(rate(fuse_request_latency_microseconds{fuse_request="flush"}[$__rate_interval]))', "µs",
        "flush is the slowest FUSE op (measured p99 2.13s under load, still 156ms when "
        "nearly idle). It is inherent to S3 object semantics: close() must wait for the "
        "multipart upload to complete. Applications doing frequent open/close of small "
        "files experience SECONDS of latency, not the 185ms that 'write' suggests.")

# ============================================================
# Row 3: IO size
# ============================================================
row("FUSE IO Size", 43)
heatmap("FUSE IO size distribution — heatmap", 0, 44, 12, 8,
        "sum(rate(fuse_io_size_bytes[$__rate_interval]))", "bytes",
        "Bytes per FUSE request. Reveals small-IO vs large-IO workload mix.")
timeseries("FUSE IO size percentiles", 12, 44, 12, 8, [
    target("histogram_quantile(0.50, sum by (fuse_request) (rate(fuse_io_size_bytes[$__rate_interval])))", "p50 {{fuse_request}}"),
    target("histogram_quantile(0.99, sum by (fuse_request) (rate(fuse_io_size_bytes[$__rate_interval])))", "p99 {{fuse_request}}"),
], "bytes",
    "FUSE-visible size != application request size. Writes pass through 1:1 "
    "(avg 1024KB from 1MiB app writes). READS get split/merged by the kernel and the "
    "amount VARIES with app block size and concurrency -- measured p50 249KB / avg "
    "213KB for a single 1MiB sequential reader, but p50 4KB / avg 74KB once a 64K "
    "reader and concurrent writers were added. Never assume the app's bs value here, "
    "and do not treat any single ratio as a constant.")
timeseries("Throughput by FUSE request type", 0, 52, 12, 7, [
    target("sum by (fuse_request) (histogram_sum(rate(fuse_io_size_bytes[$__rate_interval])))", "{{fuse_request}}"),
], "Bps", "FUSE-layer bytes only; excludes page-cache hits (see Overview note).", stack=True)
timeseries("Avg IO size by request type", 12, 52, 12, 7, [
    target("histogram_avg(sum by (fuse_request) (rate(fuse_io_size_bytes[$__rate_interval])))", "{{fuse_request}}"),
], "bytes")

# ============================================================
# Row 4: S3 API latency
# ------------------------------------------------------------
# TTFB vs TOTAL must always be read together -- see the ratio panel in Overview.
# ============================================================
row("S3 API Requests", 59)
heatmap("S3 first-byte latency (TTFB) — heatmap", 0, 60, 12, 9,
        "sum(rate(s3_request_first_byte_latency_microseconds[$__rate_interval]))", "µs",
        "Time from S3 request start until first byte received. This reflects S3 "
        "server-side responsiveness. Measured: barely changed between light and heavy "
        "load (UploadPart 158ms -> 138ms), i.e. S3 did NOT degrade.")
timeseries("S3 TTFB percentiles by API", 12, 60, 12, 9, [
    target("histogram_quantile(0.50, sum by (s3_request) (rate(s3_request_first_byte_latency_microseconds[$__rate_interval])))", "p50 {{s3_request}}"),
    target("histogram_quantile(0.99, sum by (s3_request) (rate(s3_request_first_byte_latency_microseconds[$__rate_interval])))", "p99 {{s3_request}}"),
], "µs", "", log=2)

heatmap("S3 total latency — heatmap", 0, 69, 12, 9,
        "sum(rate(s3_request_total_latency_microseconds[$__rate_interval]))", "µs",
        "Full request duration including body transfer. Measured heavy write: "
        "UploadPart TOTAL p99 1.34s vs TTFB p99 138ms -> the extra ~1.2s is spent "
        "pushing the 8MB body over the wire (local bandwidth), not waiting on S3.")
timeseries("S3 total latency percentiles by API", 12, 69, 12, 9, [
    target("histogram_quantile(0.50, sum by (s3_request) (rate(s3_request_total_latency_microseconds[$__rate_interval])))", "p50 {{s3_request}}"),
    target("histogram_quantile(0.99, sum by (s3_request) (rate(s3_request_total_latency_microseconds[$__rate_interval])))", "p99 {{s3_request}}"),
], "µs", "", log=2)

timeseries("S3 request rate by API", 0, 78, 12, 7, [
    target("sum by (s3_request) (rate(s3_request_count_total[$__rate_interval]))", "{{s3_request}}"),
], "reqps", "", stack=True)
timeseries("S3 errors by API / HTTP status (full breakdown incl. benign)", 12, 78, 12, 7, [
    target("sum by (s3_request, http_status) (rate(s3_request_errors_total[$__rate_interval]))",
           "{{s3_request}} / {{http_status}}"),
], "short",
    "Keep the http_status breakdown -- this is the panel that prevents misdiagnosis. "
    "404 and -1 are benign (see Overview). Real trouble looks like 503 (SlowDown -> "
    "reduce concurrency / spread prefixes) or other 5xx.")

# ============================================================
# Row 5: Internals
# ============================================================
row("Mountpoint Internals", 85)
timeseries("FUSE worker thread pool (--max-threads default 16)", 0, 86, 8, 7, [
    target("histogram_avg(experimental_fuse_idle_threads)", "avg idle"),
    target("histogram_quantile(0.01, experimental_fuse_idle_threads)", "p1 idle (worst case)"),
    target("16 - histogram_avg(experimental_fuse_idle_threads)", "in use (16 - idle)"),
], "short",
    "Idle threads near 0 = FUSE thread pool saturated -> raise --max-threads. "
    "Measured avg idle: 14.0 write-only, 10.4 read-only, 11.0 mixed read+write. "
    "p1 idle (worst case) is the line that matters: it hit 4.0 under mixed load "
    "(alert threshold is 3) while avg still read a comfortable 11.0 -- the average "
    "hides transient saturation. "
    "NOTE: queried WITHOUT rate() -- idle_threads is an instantaneous distribution, "
    "not a cumulative counter; wrapping it in rate() (as v1/v2 did) was wrong. "
    "experimental_fuse_total_threads_ratio is intentionally omitted: it DOES report "
    "data but is constant at 16 (= --max-threads), so it carries no information. "
    "(v2 wrongly called it a dead series -- that was an instant-query sampling gap.)")
timeseries("Process memory (RSS)", 8, 86, 8, 7, [
    target("process_memory_usage_bytes", "RSS"),
], "bytes",
    "Measured 80MB idle -> 617MB write -> 978MB read (12x) on a 7.8GB instance, still "
    "climbing during the read phase. Easily the most overlooked alertable signal here.",
    thresholds=[(2147483648, "orange")])
timeseries("FUSE errors by request type (app-visible failures)", 16, 86, 8, 7, [
    target("sum by (fuse_request) (rate(fuse_request_errors_total[$__rate_interval]))", "{{fuse_request}}"),
], "short",
    "Stayed empty through the whole 2026-07-27 test: the S3 layer had transient events "
    "but Mountpoint retried every one of them, so the application saw zero errors. "
    "Any line appearing here is a genuine problem.")

dashboard = {
    "annotations": {"list": []},
    "editable": True,
    "graphTooltip": 1,
    "links": [],
    "panels": panels,
    "refresh": "30s",
    "schemaVersion": 39,
    "tags": ["mountpoint-s3", "otlp", "native-histogram", "s3"],
    "templating": {"list": [{
        "current": {"selected": False, "text": "Prometheus-Mountpoint", "value": ""},
        "hide": 0, "includeAll": False, "label": "Datasource", "multi": False,
        "name": "DS_PROM_MP", "options": [], "query": "prometheus",
        "refresh": 1, "regex": "", "skipUrlSync": False, "type": "datasource",
    }]},
    "time": {"from": "now-1h", "to": "now"},
    "timepicker": {},
    "timezone": "",
    "title": "Mountpoint-S3 Metrics (OTLP / native histogram)",
    "uid": "mountpoint-s3-otlp",
    "version": 3,
    "weekStart": "",
}

if __name__ == "__main__":
    _fix_refids()
    dups = []
    for p in panels:
        ids = [t.get("refId") for t in p.get("targets", []) or []]
        if len(ids) != len(set(ids)):
            dups.append((p["title"], ids))
    assert not dups, "duplicate refIds: %r" % dups
    with open("mountpoint_dashboard.json", "w") as f:
        json.dump(dashboard, f, indent=2)
    print("panels:", len([p for p in panels if p["type"] != "row"]),
          "rows:", len([p for p in panels if p["type"] == "row"]),
          "| refId check: OK")
