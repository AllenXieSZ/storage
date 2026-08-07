package main

import (
	"context"
	"fmt"
	"io"
	"os"
	"sync"
	"sync/atomic"
	"time"

	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// 从环境变量读取，避免硬编码 bucket 名
var bucket = envOr("S3_BUCKET", "YOUR_BUCKET")
var key = envOr("S3_KEY", "ckpt-bench/ckpt_100g.bin")

func main() {
	ctx := context.Background()
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(envOr("AWS_REGION", "us-east-2")))
	if err != nil {
		panic(err)
	}
	client := s3.NewFromConfig(cfg)

	head, err := client.HeadObject(ctx, &s3.HeadObjectInput{Bucket: ptr(bucket), Key: ptr(key)})
	if err != nil {
		panic(err)
	}
	total := *head.ContentLength

	type cfgT struct {
		partMB int64
		conc   int
	}
	// 测试矩阵: (part_size_MB, concurrency)
	for _, tc := range []cfgT{{8, 128}, {8, 256}, {16, 256}, {8, 512}} {
		part := tc.partMB * 1024 * 1024
		nparts := (total + part - 1) / part
		var counter int64
		sem := make(chan struct{}, tc.conc) // 控制同时 in-flight 的 byte-range GET 数
		var wg sync.WaitGroup
		t0 := time.Now()
		for i := int64(0); i < nparts; i++ {
			start := i * part
			end := min64(start+part, total) - 1
			rng := fmt.Sprintf("bytes=%d-%d", start, end)
			sem <- struct{}{}
			wg.Add(1)
			go func(r string) {
				defer wg.Done()
				defer func() { <-sem }()
				out, err := client.GetObject(ctx, &s3.GetObjectInput{Bucket: ptr(bucket), Key: ptr(key), Range: ptr(r)})
				if err != nil {
					panic(err)
				}
				n, _ := io.Copy(io.Discard, out.Body) // 流式丢弃，纯测 S3->内存传输
				out.Body.Close()
				atomic.AddInt64(&counter, n)
			}(rng)
		}
		wg.Wait()
		dt := time.Since(t0).Seconds()
		gb := float64(counter) / 1e9
		fmt.Printf("[go] part=%dMB conc=%d | %6.1fs | %6.1fGB | %5.2f GB/s (%5.1f Gbps)\n",
			tc.partMB, tc.conc, dt, gb, gb/dt, gb*8/dt)
	}
}

func ptr(s string) *string { return &s }
func min64(a, b int64) int64 {
	if a < b {
		return a
	}
	return b
}
func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}
