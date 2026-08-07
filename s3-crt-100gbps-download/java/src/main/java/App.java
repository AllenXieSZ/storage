import software.amazon.awssdk.core.ResponseInputStream;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.*;
import software.amazon.awssdk.http.apache.ApacheHttpClient;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

public class App {
  // 从环境变量读取，避免硬编码 bucket 名
  static final String BUCKET = System.getenv().getOrDefault("S3_BUCKET", "YOUR_BUCKET");
  static final String KEY    = System.getenv().getOrDefault("S3_KEY", "ckpt-bench/ckpt_100g.bin");

  public static void main(String[] a) throws Exception {
    int[][] cfgs = {{8,128},{8,256},{16,256},{8,512}}; // (part_MB, concurrency)
    for (int[] tc : cfgs) {
      int partMB=tc[0], conc=tc[1];
      S3Client s3 = S3Client.builder().region(Region.US_EAST_2)
        .httpClient(ApacheHttpClient.builder().maxConnections(conc+16).build()).build();
      long total = s3.headObject(HeadObjectRequest.builder().bucket(BUCKET).key(KEY).build()).contentLength();
      long part = (long)partMB*1024*1024;
      long nparts = (total+part-1)/part;
      ExecutorService ex = Executors.newFixedThreadPool(conc);
      AtomicLong counter = new AtomicLong(0);
      long t0=System.nanoTime();
      List<Future<?>> fs = new ArrayList<>();
      for (long i=0;i<nparts;i++){
        long start=i*part, end=Math.min(start+part,total)-1;
        String rng="bytes="+start+"-"+end;
        fs.add(ex.submit(()->{
          try(ResponseInputStream<GetObjectResponse> in = s3.getObject(
              GetObjectRequest.builder().bucket(BUCKET).key(KEY).range(rng).build())){
            byte[] buf=new byte[1024*1024]; int n; long tot=0;
            while((n=in.read(buf))>0) tot+=n; // 流式丢弃，纯测 S3->内存传输
            counter.addAndGet(tot);
          } catch(Exception e){ throw new RuntimeException(e);}
        }));
      }
      for(Future<?> f: fs) f.get();
      ex.shutdown();
      double dt=(System.nanoTime()-t0)/1e9;
      double gb=counter.get()/1e9;
      System.out.printf("[java] part=%dMB conc=%d | %6.1fs | %6.1fGB | %5.2f GB/s (%5.1f Gbps)%n",
        partMB, conc, dt, gb, gb/dt, gb*8/dt);
      s3.close();
    }
  }
}
