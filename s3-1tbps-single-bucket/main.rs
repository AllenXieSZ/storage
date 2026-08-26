// S3 throughput load generator (Rust + tokio)
// 对单个 bucket 里的大对象做大量并发 ranged GET，丢弃字节，测纯下载吞吐。
// 用法: s3tp <bucket> <region> <concurrency> <duration_secs> <chunk_mb>
// 直接用 S3 REST (virtual-hosted, 走 gateway endpoint 的私网路径) + SigV4 via aws-sdk presign 太重，
// 这里用 aws-sdk-s3 的 get_object + Range，读流丢弃。

use aws_sdk_s3::Client;
use std::sync::atomic::{AtomicU64, AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

#[tokio::main(flavor = "multi_thread")]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 6 {
        eprintln!("usage: {} <bucket> <region> <concurrency> <duration_secs> <chunk_mb>", args[0]);
        std::process::exit(1);
    }
    let bucket = args[1].clone();
    let region = args[2].clone();
    let concurrency: usize = args[3].parse().unwrap();
    let duration: u64 = args[4].parse().unwrap();
    let chunk_mb: u64 = args[5].parse().unwrap();
    let chunk: u64 = chunk_mb * 1024 * 1024;

    let cfg = aws_config::defaults(aws_config::BehaviorVersion::latest())
        .region(aws_config::Region::new(region.clone()))
        .load()
        .await;
    let client = Client::new(&cfg);

    // list objects
    let mut keys: Vec<(String, u64)> = Vec::new();
    let mut cont: Option<String> = None;
    loop {
        let mut req = client.list_objects_v2().bucket(&bucket).max_keys(1000);
        if let Some(c) = &cont { req = req.continuation_token(c); }
        let resp = req.send().await.expect("list failed");
        for o in resp.contents() {
            keys.push((o.key().unwrap().to_string(), o.size().unwrap_or(0) as u64));
        }
        if resp.is_truncated().unwrap_or(false) {
            cont = resp.next_continuation_token().map(|s| s.to_string());
        } else { break; }
    }
    if keys.is_empty() { eprintln!("no objects in bucket"); std::process::exit(1); }
    println!("objects={} concurrency={} duration={}s chunk={}MB", keys.len(), concurrency, duration, chunk_mb);

    let total_bytes = Arc::new(AtomicU64::new(0));
    let total_reqs = Arc::new(AtomicU64::new(0));
    let errors = Arc::new(AtomicU64::new(0));
    let stop = Arc::new(AtomicBool::new(false));
    let keys = Arc::new(keys);

    let start = Instant::now();

    // reporter
    {
        let tb = total_bytes.clone();
        let er = errors.clone();
        let rq = total_reqs.clone();
        let stop_r = stop.clone();
        tokio::spawn(async move {
            let mut last = 0u64;
            let mut last_t = Instant::now();
            loop {
                tokio::time::sleep(Duration::from_secs(2)).await;
                if stop_r.load(Ordering::Relaxed) { break; }
                let now = tb.load(Ordering::Relaxed);
                let dt = last_t.elapsed().as_secs_f64();
                let gbps = ((now - last) as f64 * 8.0) / dt / 1e9;
                let gBps = (now - last) as f64 / dt / 1e9;
                println!("[+{:>4.0}s] {:.1} Gbps ({:.2} GB/s)  reqs={} errs={}",
                    start.elapsed().as_secs_f64(), gbps, gBps,
                    rq.load(Ordering::Relaxed), er.load(Ordering::Relaxed));
                last = now; last_t = Instant::now();
            }
        });
    }

    let mut handles = Vec::new();
    for w in 0..concurrency {
        let client = client.clone();
        let bucket = bucket.clone();
        let keys = keys.clone();
        let tb = total_bytes.clone();
        let rq = total_reqs.clone();
        let er = errors.clone();
        let stop = stop.clone();
        handles.push(tokio::spawn(async move {
            let mut seed = (w as u64).wrapping_mul(2654435761) ^ 0x9e3779b97f4a7c15;
            let mut buf = vec![0u8; 1024 * 1024];
            while !stop.load(Ordering::Relaxed) {
                // pick random object + random offset
                seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
                let (key, size) = &keys[(seed >> 33) as usize % keys.len()];
                if *size == 0 { continue; }
                let max_off = if *size > chunk { *size - chunk } else { 0 };
                seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
                let off = if max_off > 0 { (seed >> 33) % max_off } else { 0 };
                let end = (off + chunk - 1).min(*size - 1);
                let range = format!("bytes={}-{}", off, end);
                match client.get_object().bucket(&bucket).key(key).range(range).send().await {
                    Ok(mut o) => {
                        let mut n: u64 = 0;
                        loop {
                            match o.body.try_next().await {
                                Ok(Some(bytes)) => { n += bytes.len() as u64; let _ = &buf; }
                                Ok(None) => break,
                                Err(_) => { er.fetch_add(1, Ordering::Relaxed); break; }
                            }
                        }
                        tb.fetch_add(n, Ordering::Relaxed);
                        rq.fetch_add(1, Ordering::Relaxed);
                    }
                    Err(_) => { er.fetch_add(1, Ordering::Relaxed); }
                }
            }
        }));
    }

    tokio::time::sleep(Duration::from_secs(duration)).await;
    stop.store(true, Ordering::Relaxed);
    for h in handles { let _ = h.await; }

    let elapsed = start.elapsed().as_secs_f64();
    let tot = total_bytes.load(Ordering::Relaxed);
    let avg_gbps = (tot as f64 * 8.0) / elapsed / 1e9;
    println!("==== DONE ====");
    println!("total={:.1} GB  elapsed={:.1}s  AVG={:.1} Gbps ({:.2} GB/s)  reqs={} errs={}",
        tot as f64 / 1e9, elapsed, avg_gbps, tot as f64 / elapsed / 1e9,
        total_reqs.load(Ordering::Relaxed), errors.load(Ordering::Relaxed));
}
