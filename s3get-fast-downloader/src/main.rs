// s3get — 高速并发下载 S3 大文件到本地磁盘
//
// 用法:
//   s3get <S3路径> <region> <本地路径> [选项]
//
// S3路径 支持两种写法:
//   s3://bucket/path/to/key
//   bucket/path/to/key
//
// 示例:
//   s3get s3://my-bucket/data/big.bin us-east-2 /data/big.bin
//   s3get my-bucket/data/big.bin us-east-2 ./big.bin --concurrency 256 --part-size 16
//
// 凭证: 自动使用 AWS 默认凭证链(~/.aws/credentials、环境变量 AWS_ACCESS_KEY_ID/
//       AWS_SECRET_ACCESS_KEY、EC2/ECS IAM role 等),和 AWS CLI 一致。
//       可用 --profile 指定 ~/.aws 中的具体 profile。

use aws_sdk_s3::Client;
use clap::Parser;
use std::os::unix::fs::FileExt;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Instant;

#[derive(Parser, Debug)]
#[command(
    name = "s3get",
    version,
    about = "高速并发下载 S3 大文件到本地磁盘 (读取 AWS CLI 凭证)"
)]
struct Args {
    /// S3 路径: s3://bucket/key 或 bucket/key
    s3_path: String,

    /// AWS Region, 例如 us-east-2
    region: String,

    /// 本地输出路径(文件名或目录; 目录则用 key 的文件名)
    local_path: String,

    /// 每个分片大小 (MB), 默认 8
    #[arg(long, default_value_t = 8)]
    part_size: u64,

    /// 并发 range 请求数, 默认 256 (实测可打满 ~96Gbps)
    #[arg(long, default_value_t = 256)]
    concurrency: usize,

    /// AWS 配置 profile 名 (~/.aws/credentials 中的 [profile]), 默认用 default 链
    #[arg(long)]
    profile: Option<String>,

    /// 只打印计划不下载 (dry-run)
    #[arg(long, default_value_t = false)]
    dry_run: bool,
}

fn parse_s3_path(s: &str) -> (String, String) {
    let trimmed = s.strip_prefix("s3://").unwrap_or(s);
    match trimmed.split_once('/') {
        Some((b, k)) => (b.to_string(), k.to_string()),
        None => {
            eprintln!("错误: S3 路径必须是 s3://bucket/key 或 bucket/key 形式");
            std::process::exit(2);
        }
    }
}

#[tokio::main]
async fn main() {
    let args = Args::parse();
    let (bucket, key) = parse_s3_path(&args.s3_path);

    // 若本地路径是已存在的目录, 追加 key 的文件名
    let mut out_path = args.local_path.clone();
    if std::path::Path::new(&out_path).is_dir() {
        let fname = key.rsplit('/').next().unwrap_or("download.bin");
        out_path = format!("{}/{}", out_path.trim_end_matches('/'), fname);
    }

    // 构建 AWS 配置: region + 默认凭证链 (+可选 profile)
    let region = aws_config::Region::new(args.region.clone());
    let mut loader = aws_config::defaults(aws_config::BehaviorVersion::latest())
        .region(region)
        // 关闭 stalled-stream protection: 高并发+带宽拥塞时单个流可能短暂读到0字节,
        // 默认保护会误判为 stalled 而 panic(ThroughputBelowMinimum)。下载器需容忍拥塞。
        .stalled_stream_protection(
            aws_config::stalled_stream_protection::StalledStreamProtectionConfig::disabled(),
        );
    if let Some(p) = &args.profile {
        loader = loader.profile_name(p);
    }
    let cfg = loader.load().await;
    let client = Client::new(&cfg);

    // HEAD 取对象大小
    let head = match client.head_object().bucket(&bucket).key(&key).send().await {
        Ok(h) => h,
        Err(e) => {
            eprintln!("错误: HEAD s3://{}/{} 失败: {}", bucket, key, e);
            std::process::exit(1);
        }
    };
    let total: u64 = head.content_length().unwrap_or(0) as u64;
    if total == 0 {
        eprintln!("错误: 对象大小为 0 或无法获取");
        std::process::exit(1);
    }

    let part = args.part_size * 1024 * 1024;
    let nparts = (total + part - 1) / part;

    println!("对象: s3://{}/{}", bucket, key);
    println!("大小: {:.2} GB ({} bytes)", total as f64 / 1e9, total);
    println!("输出: {}", out_path);
    println!(
        "计划: {} 个分片 x {}MB, 并发 {}",
        nparts, args.part_size, args.concurrency
    );
    if args.dry_run {
        println!("(dry-run, 不下载)");
        return;
    }

    // 预分配输出文件到目标大小 (稀疏文件, 允许并发 pwrite 到各自 offset)
    let file = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&out_path)
        .unwrap_or_else(|e| {
            eprintln!("错误: 无法创建输出文件 {}: {}", out_path, e);
            std::process::exit(1);
        });
    file.set_len(total).ok();
    let file = Arc::new(file);

    let counter = Arc::new(AtomicU64::new(0));
    let sem = Arc::new(tokio::sync::Semaphore::new(args.concurrency));
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
        let f = file.clone();
        let permit = sem.clone().acquire_owned().await.unwrap();
        handles.push(tokio::spawn(async move {
            let _p = permit; // drop 释放并发额度
            // 每个分片独立重试: 连接重置/超时等瞬时错误自动重试, 单片失败不影响整体
            let max_retries = 5u32;
            let mut attempt = 0u32;
            loop {
                attempt += 1;
                let r: Result<u64, String> = async {
                    let resp = c
                        .get_object()
                        .bucket(&b)
                        .key(&k)
                        .range(range.clone())
                        .send()
                        .await
                        .map_err(|e| format!("get_object: {}", e))?;
                    let mut body = resp.body;
                    let mut offset = start;
                    let mut got: u64 = 0;
                    while let Some(bytes) = body
                        .try_next()
                        .await
                        .map_err(|e| format!("read body: {}", e))?
                    {
                        f.write_all_at(&bytes, offset).map_err(|e| format!("write: {}", e))?;
                        offset += bytes.len() as u64;
                        got += bytes.len() as u64;
                    }
                    Ok(got)
                }
                .await;
                match r {
                    Ok(got) => {
                        cnt.fetch_add(got, Ordering::Relaxed);
                        break;
                    }
                    Err(e) => {
                        if attempt >= max_retries {
                            eprintln!("分片 {} 重试 {} 次仍失败: {}", range, max_retries, e);
                            std::process::exit(1);
                        }
                        // 指数退避
                        tokio::time::sleep(std::time::Duration::from_millis(
                            200 * 2u64.pow(attempt - 1),
                        ))
                        .await;
                    }
                }
            }
        }));
    }
    for h in handles {
        h.await.unwrap();
    }
    file.sync_all().ok();

    let dt = t0.elapsed().as_secs_f64();
    let gb = counter.load(Ordering::Relaxed) as f64 / 1e9;
    println!(
        "完成: {:.2} GB / {:.1}s = {:.2} GB/s ({:.1} Gbps)",
        gb,
        dt,
        gb / dt,
        gb * 8.0 / dt
    );
}
