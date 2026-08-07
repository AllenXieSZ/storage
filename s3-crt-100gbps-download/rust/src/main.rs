use aws_sdk_s3::Client;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Instant;

// 从环境变量读取，避免硬编码 bucket 名:
//   export S3_BUCKET=your-bucket S3_KEY=ckpt-bench/ckpt_100g.bin
fn env_or(k: &str, d: &str) -> String {
    std::env::var(k).unwrap_or_else(|_| d.to_string())
}

#[tokio::main]
async fn main() {
    let bucket = env_or("S3_BUCKET", "YOUR_BUCKET");
    let key = env_or("S3_KEY", "ckpt-bench/ckpt_100g.bin");
    let region_str = env_or("AWS_REGION", "us-east-2");

    let region = aws_config::meta::region::RegionProviderChain::default_provider()
        .or_else(aws_config::Region::new(region_str));
    let cfg = aws_config::defaults(aws_config::BehaviorVersion::latest())
        .region(region)
        .load()
        .await;
    let client = Client::new(&cfg);

    // HEAD 取对象大小
    let head = client.head_object().bucket(&bucket).key(&key).send().await.unwrap();
    let total: u64 = head.content_length().unwrap() as u64;

    // 测试矩阵: (part_size_MB, concurrency)
    for (part_mb, concurrency) in [(8u64, 64usize), (8, 128), (8, 256), (16, 128), (16, 256)] {
        let part = part_mb * 1024 * 1024;
        let nparts = (total + part - 1) / part;
        let counter = Arc::new(AtomicU64::new(0));
        // Semaphore 控制同时 in-flight 的 byte-range GET 数量 = concurrency
        let sem = Arc::new(tokio::sync::Semaphore::new(concurrency));
        let t0 = Instant::now();
        let mut handles = Vec::new();
        for i in 0..nparts {
            let start = i * part;
            let end = std::cmp::min(start + part, total) - 1;
            let range = format!("bytes={}-{}", start, end);
            let c = client.clone();
            let b = bucket.clone();
            let k = key.clone();
            let cnt = counter.clone();
            let permit = sem.clone().acquire_owned().await.unwrap();
            handles.push(tokio::spawn(async move {
                let _p = permit; // drop 时释放并发额度
                let resp = c.get_object().bucket(&b).key(&k).range(range).send().await.unwrap();
                let mut body = resp.body;
                let mut n: u64 = 0;
                // 流式读取 body 并丢弃(纯测 S3 -> 内存传输吞吐, 不落盘)
                while let Some(bytes) = body.try_next().await.unwrap() {
                    n += bytes.len() as u64;
                }
                cnt.fetch_add(n, Ordering::Relaxed);
            }));
        }
        for h in handles {
            h.await.unwrap();
        }
        let dt = t0.elapsed().as_secs_f64();
        let gb = counter.load(Ordering::Relaxed) as f64 / 1e9;
        println!(
            "part={:>3}MB concurrency={:>3} | {:6.1}s | {:6.1}GB | {:5.2} GB/s ({:5.1} Gbps)",
            part_mb, concurrency, dt, gb, gb / dt, gb * 8.0 / dt
        );
    }
}
