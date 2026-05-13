#!/usr/bin/env python3
"""
S3 Benchmark Script - Standard vs Express One Zone Comparison
Tests:
1. Object I/O latency (PUT/GET) for 4KB, 4MB, 8MB objects
2. Bucket throughput: multipart upload and range GET for large files (1GB)

Generates an HTML comparison report.
"""

import boto3
import time
import json
import os
import statistics
import sys
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import Pool, cpu_count
import multiprocessing

# Configuration
REGION = os.environ.get("BENCH_REGION", "us-east-2")
AZ_ID = os.environ.get("BENCH_AZ_ID", "use2-az1")  # AZ ID for Express One Zone
STANDARD_BUCKET = os.environ.get("BENCH_BUCKET_STD", "")
EXPRESS_BUCKET = os.environ.get("BENCH_BUCKET_EXPRESS", "")
ITERATIONS = int(os.environ.get("BENCH_ITERATIONS", "20"))
LARGE_FILE_SIZE = 1024 * 1024 * 1024  # 1GB for throughput test
MULTIPART_CHUNK = 64 * 1024 * 1024  # 64MB chunks (optimized from testing)
RANGE_CHUNK = 64 * 1024 * 1024  # 64MB range reads (optimized from testing)
CONCURRENCY = int(os.environ.get("BENCH_CONCURRENCY", "128"))
THROUGHPUT_RUNS = 3

OBJECT_SIZES = {
    "4KB": 4 * 1024,
    "4MB": 4 * 1024 * 1024,
    "8MB": 8 * 1024 * 1024,
}


def create_s3_client():
    return boto3.client("s3", region_name=REGION)


def create_s3express_client():
    """Create S3 client for Express One Zone (uses CreateSession auth)."""
    return boto3.client("s3", region_name=REGION)


def generate_data(size):
    return os.urandom(size)


def test_put_latency(s3, bucket, key, data, iterations):
    latencies = []
    for i in range(iterations):
        start = time.perf_counter()
        s3.put_object(Bucket=bucket, Key=key, Body=data)
        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)
    return latencies


def test_get_latency(s3, bucket, key, iterations):
    latencies = []
    for i in range(iterations):
        start = time.perf_counter()
        resp = s3.get_object(Bucket=bucket, Key=key)
        resp["Body"].read()
        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)
    return latencies


def test_multipart_upload(s3, bucket, key, total_size, chunk_size, concurrency):
    data = generate_data(total_size)
    num_parts = (total_size + chunk_size - 1) // chunk_size

    mpu = s3.create_multipart_upload(Bucket=bucket, Key=key)
    upload_id = mpu["UploadId"]

    start = time.perf_counter()

    def upload_part(part_num):
        offset = (part_num - 1) * chunk_size
        end = min(offset + chunk_size, total_size)
        part_data = data[offset:end]
        resp = s3.upload_part(
            Bucket=bucket, Key=key, UploadId=upload_id,
            PartNumber=part_num, Body=part_data
        )
        return {"PartNumber": part_num, "ETag": resp["ETag"]}

    parts = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(upload_part, i) for i in range(1, num_parts + 1)]
        for f in as_completed(futures):
            parts.append(f.result())

    parts.sort(key=lambda x: x["PartNumber"])
    s3.complete_multipart_upload(
        Bucket=bucket, Key=key, UploadId=upload_id,
        MultipartUpload={"Parts": parts}
    )

    elapsed = time.perf_counter() - start
    throughput_mbps = (total_size / (1024 * 1024)) / elapsed
    return elapsed, throughput_mbps


def _range_get_worker(args):
    """Worker for multiprocessing range GET (bypass GIL)."""
    bucket, key, offset, end, region = args
    s3 = boto3.client("s3", region_name=region)
    resp = s3.get_object(Bucket=bucket, Key=key, Range=f"bytes={offset}-{end}")
    resp["Body"].read()


def test_range_get(s3, bucket, key, total_size, chunk_size, concurrency):
    """Test range GET throughput using multiprocessing (bypass GIL)."""
    num_ranges = (total_size + chunk_size - 1) // chunk_size

    worker_args = []
    for i in range(num_ranges):
        offset = i * chunk_size
        end = min(offset + chunk_size - 1, total_size - 1)
        worker_args.append((bucket, key, offset, end, REGION))

    start = time.perf_counter()

    num_workers = min(32, num_ranges, cpu_count() * 2)
    with Pool(processes=num_workers) as pool:
        pool.map(_range_get_worker, worker_args)

    elapsed = time.perf_counter() - start
    throughput_mbps = (total_size / (1024 * 1024)) / elapsed
    return elapsed, throughput_mbps


def calc_stats(latencies):
    return {
        "min": round(min(latencies), 2),
        "max": round(max(latencies), 2),
        "avg": round(statistics.mean(latencies), 2),
        "p50": round(sorted(latencies)[len(latencies) // 2], 2),
        "p90": round(sorted(latencies)[int(len(latencies) * 0.9)], 2),
        "p99": round(sorted(latencies)[int(len(latencies) * 0.99)], 2),
        "stddev": round(statistics.stdev(latencies) if len(latencies) > 1 else 0, 2),
    }


def run_single_bucket_benchmark(s3, bucket, bucket_type):
    """Run benchmarks on a single bucket."""
    results = {"latency": {}, "throughput": {}}

    print(f"\n{'='*60}")
    print(f"  {bucket_type} BENCHMARK")
    print(f"  Bucket: {bucket}")
    print(f"{'='*60}")

    # --- Latency Tests ---
    print(f"\n  OBJECT I/O LATENCY ({bucket_type})")
    print(f"  {'-'*40}")

    for size_name, size_bytes in OBJECT_SIZES.items():
        print(f"\n  --- {size_name} Object ---")
        key = f"bench/latency-{size_name}"
        data = generate_data(size_bytes)

        print(f"    PUT x{ITERATIONS}...", end=" ", flush=True)
        put_latencies = test_put_latency(s3, bucket, key, data, ITERATIONS)
        put_stats = calc_stats(put_latencies)
        print(f"avg={put_stats['avg']}ms p50={put_stats['p50']}ms p90={put_stats['p90']}ms")

        print(f"    GET x{ITERATIONS}...", end=" ", flush=True)
        get_latencies = test_get_latency(s3, bucket, key, ITERATIONS)
        get_stats = calc_stats(get_latencies)
        print(f"avg={get_stats['avg']}ms p50={get_stats['p50']}ms p90={get_stats['p90']}ms")

        results["latency"][size_name] = {
            "put": {"stats": put_stats, "raw": [round(x, 2) for x in put_latencies]},
            "get": {"stats": get_stats, "raw": [round(x, 2) for x in get_latencies]},
        }

        s3.delete_object(Bucket=bucket, Key=key)

    # --- Throughput Tests ---
    print(f"\n  BUCKET THROUGHPUT ({bucket_type})")
    print(f"  File: {LARGE_FILE_SIZE//(1024*1024)}MB | Chunk: {MULTIPART_CHUNK//(1024*1024)}MB | Concurrency: {CONCURRENCY}")
    print(f"  {'-'*40}")

    throughput_key = "bench/throughput-large-file"

    # Multipart Upload
    print(f"\n    Multipart Upload ({LARGE_FILE_SIZE//(1024*1024)}MB)...", end=" ", flush=True)
    upload_runs = []
    for i in range(THROUGHPUT_RUNS):
        elapsed, tp = test_multipart_upload(
            s3, bucket, throughput_key, LARGE_FILE_SIZE, MULTIPART_CHUNK, CONCURRENCY
        )
        upload_runs.append({"elapsed_s": round(elapsed, 2), "throughput_mbps": round(tp, 2)})
        print(f"run{i+1}={tp:.1f}MB/s", end=" ", flush=True)
        if i < THROUGHPUT_RUNS - 1:
            s3.delete_object(Bucket=bucket, Key=throughput_key)
    print()

    results["throughput"]["multipart_upload"] = {
        "runs": upload_runs,
        "avg_throughput_mbps": round(statistics.mean([r["throughput_mbps"] for r in upload_runs]), 2),
    }

    # Range GET
    print(f"    Range GET ({LARGE_FILE_SIZE//(1024*1024)}MB, {CONCURRENCY} parallel)...", end=" ", flush=True)
    range_runs = []
    for i in range(THROUGHPUT_RUNS):
        elapsed, tp = test_range_get(
            s3, bucket, throughput_key, LARGE_FILE_SIZE, RANGE_CHUNK, CONCURRENCY
        )
        range_runs.append({"elapsed_s": round(elapsed, 2), "throughput_mbps": round(tp, 2)})
        print(f"run{i+1}={tp:.1f}MB/s", end=" ", flush=True)
    print()

    results["throughput"]["range_get"] = {
        "runs": range_runs,
        "avg_throughput_mbps": round(statistics.mean([r["throughput_mbps"] for r in range_runs]), 2),
    }

    # Cleanup
    s3.delete_object(Bucket=bucket, Key=throughput_key)

    return results


def run_benchmark():
    """Run benchmarks on both Standard and Express One Zone."""
    s3 = create_s3_client()

    all_results = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "region": REGION,
            "az_id": AZ_ID,
            "standard_bucket": STANDARD_BUCKET,
            "express_bucket": EXPRESS_BUCKET,
            "iterations": ITERATIONS,
            "large_file_size_mb": LARGE_FILE_SIZE // (1024 * 1024),
            "multipart_chunk_mb": MULTIPART_CHUNK // (1024 * 1024),
            "concurrency": CONCURRENCY,
        },
        "standard": {},
        "express": {},
    }

    # Run Standard bucket benchmark
    all_results["standard"] = run_single_bucket_benchmark(s3, STANDARD_BUCKET, "S3 STANDARD")

    # Run Express One Zone benchmark
    all_results["express"] = run_single_bucket_benchmark(s3, EXPRESS_BUCKET, "S3 EXPRESS ONE ZONE")

    return all_results


def pct_diff(express_val, standard_val):
    """Calculate percentage improvement of Express over Standard."""
    if standard_val == 0:
        return 0
    diff = ((express_val - standard_val) / standard_val) * 100
    return round(diff, 1)


def generate_html_report(results, output_path):
    """Generate comparison HTML report."""
    meta = results["metadata"]
    std = results["standard"]
    exp = results["express"]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>S3 Standard vs Express One Zone - Benchmark Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; background: #f5f5f5; color: #333; }}
  .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  h1 {{ color: #232f3e; border-bottom: 3px solid #ff9900; padding-bottom: 10px; }}
  h2 {{ color: #232f3e; margin-top: 40px; }}
  h3 {{ color: #555; }}
  .meta {{ background: #f0f4f8; padding: 15px 20px; border-radius: 6px; margin: 20px 0; font-size: 0.9em; }}
  .meta span {{ margin-right: 25px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 10px 14px; text-align: right; }}
  th {{ background: #232f3e; color: white; }}
  td:first-child, th:first-child {{ text-align: left; }}
  tr:nth-child(even) {{ background: #f9f9f9; }}
  .better {{ color: #2e7d32; font-weight: bold; }}
  .worse {{ color: #c62828; }}
  .neutral {{ color: #555; }}
  .pct-badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; font-weight: bold; }}
  .pct-good {{ background: #e8f5e9; color: #2e7d32; }}
  .pct-bad {{ background: #ffebee; color: #c62828; }}
  .pct-neutral {{ background: #f5f5f5; color: #555; }}
  .throughput-card {{ display: inline-block; background: #f5f5f5; padding: 20px 30px; border-radius: 8px; margin: 10px 10px 10px 0; text-align: center; min-width: 200px; }}
  .throughput-card .value {{ font-size: 1.8em; font-weight: bold; }}
  .throughput-card .label {{ color: #555; margin-top: 5px; font-size: 0.9em; }}
  .throughput-card.std .value {{ color: #1565c0; }}
  .throughput-card.exp .value {{ color: #ff6f00; }}
  .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #888; font-size: 0.9em; }}
  .legend {{ margin: 10px 0; font-size: 0.85em; color: #666; }}
  .section-divider {{ border: none; border-top: 2px solid #ff9900; margin: 40px 0; }}
  .summary-box {{ background: linear-gradient(135deg, #fff3e0, #e8f5e9); padding: 20px; border-radius: 8px; margin: 20px 0; }}
  .summary-box h3 {{ margin-top: 0; }}
</style>
</head>
<body>
<div class="container">
<h1>🪣 S3 Standard vs Express One Zone — Benchmark Comparison</h1>

<div class="meta">
  <span><strong>Region:</strong> {meta['region']}</span>
  <span><strong>AZ:</strong> {meta['az_id']}</span>
  <span><strong>Time:</strong> {meta['timestamp']}</span>
  <span><strong>Iterations:</strong> {meta['iterations']}</span>
  <span><strong>Concurrency:</strong> {meta['concurrency']}</span><br>
  <span><strong>Standard Bucket:</strong> {meta['standard_bucket']}</span><br>
  <span><strong>Express Bucket:</strong> {meta['express_bucket']}</span>
</div>
"""

    # --- Latency Comparison ---
    html += """
<h2>📊 Object I/O Latency Comparison</h2>
<p class="legend">Lower is better for latency. <span class="pct-badge pct-good">-XX%</span> = Express is faster, <span class="pct-badge pct-bad">+XX%</span> = Express is slower.</p>

<h3>PUT Latency (ms)</h3>
<table>
<tr><th>Size</th><th>Standard Avg</th><th>Standard P50</th><th>Standard P90</th><th>Express Avg</th><th>Express P50</th><th>Express P90</th><th>Δ Avg</th></tr>
"""

    for size_name in OBJECT_SIZES:
        if size_name in std["latency"] and size_name in exp["latency"]:
            s = std["latency"][size_name]["put"]["stats"]
            e = exp["latency"][size_name]["put"]["stats"]
            diff = pct_diff(e["avg"], s["avg"])
            badge_class = "pct-good" if diff < -5 else ("pct-bad" if diff > 5 else "pct-neutral")
            diff_str = f"+{diff}%" if diff > 0 else f"{diff}%"
            html += f'<tr><td><strong>{size_name}</strong></td><td>{s["avg"]}</td><td>{s["p50"]}</td><td>{s["p90"]}</td><td>{e["avg"]}</td><td>{e["p50"]}</td><td>{e["p90"]}</td><td><span class="pct-badge {badge_class}">{diff_str}</span></td></tr>\n'

    html += """</table>

<h3>GET Latency (ms)</h3>
<table>
<tr><th>Size</th><th>Standard Avg</th><th>Standard P50</th><th>Standard P90</th><th>Express Avg</th><th>Express P50</th><th>Express P90</th><th>Δ Avg</th></tr>
"""

    for size_name in OBJECT_SIZES:
        if size_name in std["latency"] and size_name in exp["latency"]:
            s = std["latency"][size_name]["get"]["stats"]
            e = exp["latency"][size_name]["get"]["stats"]
            diff = pct_diff(e["avg"], s["avg"])
            badge_class = "pct-good" if diff < -5 else ("pct-bad" if diff > 5 else "pct-neutral")
            diff_str = f"+{diff}%" if diff > 0 else f"{diff}%"
            html += f'<tr><td><strong>{size_name}</strong></td><td>{s["avg"]}</td><td>{s["p50"]}</td><td>{s["p90"]}</td><td>{e["avg"]}</td><td>{e["p50"]}</td><td>{e["p90"]}</td><td><span class="pct-badge {badge_class}">{diff_str}</span></td></tr>\n'

    html += "</table>\n"

    # --- Throughput Comparison ---
    std_up = std["throughput"]["multipart_upload"]["avg_throughput_mbps"]
    exp_up = exp["throughput"]["multipart_upload"]["avg_throughput_mbps"]
    std_down = std["throughput"]["range_get"]["avg_throughput_mbps"]
    exp_down = exp["throughput"]["range_get"]["avg_throughput_mbps"]

    up_diff = pct_diff(exp_up, std_up)
    down_diff = pct_diff(exp_down, std_down)

    html += f"""
<hr class="section-divider">
<h2>🚀 Bucket Throughput Comparison</h2>
<p>Large file ({meta['large_file_size_mb']}MB), chunk size {meta['multipart_chunk_mb']}MB, concurrency {meta['concurrency']}.</p>
<p class="legend">Higher is better for throughput.</p>

<h3>Multipart Upload</h3>
<div>
  <div class="throughput-card std">
    <div class="value">{std_up} MB/s</div>
    <div class="label">S3 Standard</div>
  </div>
  <div class="throughput-card exp">
    <div class="value">{exp_up} MB/s</div>
    <div class="label">S3 Express One Zone</div>
  </div>
  <div class="throughput-card">
    <div class="value" style="color: {'#2e7d32' if up_diff > 0 else '#c62828'}">{'+' if up_diff > 0 else ''}{up_diff}%</div>
    <div class="label">Express vs Standard</div>
  </div>
</div>

<h3>Range GET (Parallel)</h3>
<div>
  <div class="throughput-card std">
    <div class="value">{std_down} MB/s</div>
    <div class="label">S3 Standard</div>
  </div>
  <div class="throughput-card exp">
    <div class="value">{exp_down} MB/s</div>
    <div class="label">S3 Express One Zone</div>
  </div>
  <div class="throughput-card">
    <div class="value" style="color: {'#2e7d32' if down_diff > 0 else '#c62828'}">{'+' if down_diff > 0 else ''}{down_diff}%</div>
    <div class="label">Express vs Standard</div>
  </div>
</div>

<h3>Detailed Throughput Runs</h3>
<table>
<tr><th>Test</th><th>Bucket</th><th>Run 1</th><th>Run 2</th><th>Run 3</th><th>Avg (MB/s)</th></tr>
"""

    for label, data in [("Multipart Upload", "multipart_upload"), ("Range GET", "range_get")]:
        for btype, bdata in [("Standard", std), ("Express", exp)]:
            html += f'<tr><td><strong>{label}</strong></td><td>{btype}</td>'
            for r in bdata["throughput"][data]["runs"]:
                html += f'<td>{r["throughput_mbps"]}</td>'
            html += f'<td><strong>{bdata["throughput"][data]["avg_throughput_mbps"]}</strong></td></tr>\n'

    html += "</table>\n"

    # --- Summary ---
    html += """
<hr class="section-divider">
<div class="summary-box">
<h3>📋 Summary</h3>
<ul>
"""
    # Latency summary
    for size_name in OBJECT_SIZES:
        if size_name in std["latency"] and size_name in exp["latency"]:
            put_diff = pct_diff(exp["latency"][size_name]["put"]["stats"]["avg"],
                               std["latency"][size_name]["put"]["stats"]["avg"])
            get_diff = pct_diff(exp["latency"][size_name]["get"]["stats"]["avg"],
                               std["latency"][size_name]["get"]["stats"]["avg"])
            html += f'<li><strong>{size_name}</strong>: PUT {put_diff:+.1f}%, GET {get_diff:+.1f}% (Express vs Standard)</li>\n'

    html += f'<li><strong>Multipart Upload</strong>: {up_diff:+.1f}% (Express vs Standard)</li>\n'
    html += f'<li><strong>Range GET</strong>: {down_diff:+.1f}% (Express vs Standard)</li>\n'
    html += """</ul>
<p><em>Negative % = Express is faster (lower latency). Positive % = Express is faster (higher throughput).</em></p>
</div>
"""

    html += f"""
<div class="footer">
  Generated by S3 Benchmark Script | {meta['timestamp']} | Region: {meta['region']} | AZ: {meta['az_id']}
</div>
</div>
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)
    print(f"\n✅ HTML report saved to: {output_path}")


if __name__ == "__main__":
    multiprocessing.set_start_method("fork", force=True)

    if not STANDARD_BUCKET or not EXPRESS_BUCKET:
        print("ERROR: BENCH_BUCKET_STD and BENCH_BUCKET_EXPRESS env vars must be set")
        sys.exit(1)

    print(f"S3 Standard vs Express One Zone Benchmark")
    print(f"  Region: {REGION} | AZ: {AZ_ID}")
    print(f"  Standard: {STANDARD_BUCKET}")
    print(f"  Express:  {EXPRESS_BUCKET}")
    print(f"  Iterations: {ITERATIONS} | Concurrency: {CONCURRENCY}")

    results = run_benchmark()

    json_path = "/tmp/s3_bench_results.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n✅ JSON results saved to: {json_path}")

    html_path = "/tmp/s3_bench_report.html"
    generate_html_report(results, html_path)
