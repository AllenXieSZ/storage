# npm install Storage Benchmark — Phase 3 (EFS vs S3 Files vs JuiceFS vs EBS)

Single-run `npm install` of a heavyweight front-end dependency tree (**66,513 files**) on one EC2 client, comparing **default vs optimized mount options** for each network storage backend. This is the small-file, metadata-heavy companion to [`kernel-untar-bench-4way`](../kernel-untar-bench-4way/) (`tar xf` / `git clone`).

## Why npm install
`npm install` is one of the most metadata-op-intensive real-world workloads: it creates tens of thousands of tiny files across a deep directory tree with heavy `mkdir`, `lstat`, `rename`, `open/write/close`, and `symlink` traffic. On a network filesystem every one of those turns into a synchronous round-trip, so it is a sharp test of whether mount tuning helps.

## Test setup

| Item | Value |
|---|---|
| Region | us-east-2 (Ohio) |
| Client (EC2-A) | 1× c7i.4xlarge, AL2023, gp3 100 GB @ 8000 IOPS / 500 MB/s (root xfs, noatime) |
| Redis (EC2-B, JuiceFS meta) | 1× c7i.4xlarge, gp3 30 GB |
| Node.js | v18.20.8 (LTS), npm 10.8.2 |
| Workload | `npm install --prefer-offline --no-audit --no-fund` of a heavyweight `package.json` |
| Files produced | **66,513** node_modules entries (identical every run) |
| Lockfile | one `package-lock.json` generated once, reused for **every** run |
| npm cache | primed once on local EBS (`~/.npm` = /root/.npm), so runs measure filesystem/metadata cost, not download |
| Method | `sync && echo 3 > drop_caches` before each run; fresh workdir on the target mount; `/usr/bin/time -v`; wall clock |

The dependency set: react, react-dom, vue, next, @mui/material, @emotion, antd, rxjs, lodash + dev tools (webpack, webpack-cli, webpack-dev-server, @babel/*, babel-loader, typescript, ts-loader, eslint, eslint-plugin-react, prettier, jest, @testing-library/*, @vue/cli-service, sass, sass-loader, css-loader, style-loader, postcss, postcss-loader, autoprefixer, tailwindcss, vite, @vitejs/plugin-react, storybook, @storybook/react). `package.json` and `package-lock.json` are stored in this directory for reproducibility.

## Results — npm install time (EBS = reference)

![npm install: default vs optimized mount](phase3_npm_compare.png)


| Storage | Mount (default / optimized) | npm install time | Files | Optimized vs default |
|---|---|---|---|---|
| **EBS gp3** | local, noatime (reference only) | **13.1 s** | 66,513 | — (single run) |
| **EFS (Elastic)** | default (`tls`) | **3 m 43 s** (223.1 s) | 66,513 | — |
| **EFS (Elastic)** | optimized (`noatime,nodiratime,rsize/wsize=1M,actimeo=600`) | **3 m 49 s** (228.8 s) | 66,513 | **−2.6 %** (no gain) |
| **S3 Files** | default (`tls,iam`) NFSv4.2 | **3 m 59 s** (239.4 s) | 66,513 | — |
| **S3 Files** | optimized (`+noatime,nodiratime,rsize/wsize=1M,actimeo=600`) | **3 m 59 s** (238.8 s) | 66,513 | **+0.3 %** (no gain) |
| **JuiceFS** | default (`redis + S3`, FUSE) | **7 m 12 s** (432.1 s) | 66,513 | — |
| **JuiceFS** | optimized (`--writeback --*-cache 300 --cache-size 10240 --buffer-size 1024`) | **1 m 43 s** (103.1 s) | 66,513 | **+76.1 %** faster |

## Verdict — does mount tuning help npm install?

**It depends entirely on where the bottleneck lives. Two key findings:**

> **① NFS-class stores (EFS / S3 Files): optimized mount options do essentially nothing (±3%).** The bottleneck is the per-file **synchronous metadata round-trip** (mkdir/create/rename/write each wait for a server ACK). `noatime`/`rsize/wsize=1M`/`actimeo` tune read/attribute-cache behavior and never touch that wall; `nconnect` is also silently ignored under `-o tls`.
>
> **② JuiceFS `--writeback` is the only optimization that actually works (−76%, 7m12s → 1m43s).** It makes data writes asynchronous (local buffer first, background S3 upload), taking S3 latency off the critical path — even beating both NFS stores and nearing local-disk speed. Trade-off: relaxed durability, fine for rebuildable node_modules only.


- **EFS / S3 Files: mount tuning does essentially nothing (±3%).** Both are NFS (v4.1 / v4.2) over the EFS-utils stunnel socket. The standard NFS knobs — `noatime`, `nodiratime`, `rsize/wsize=1M`, `actimeo=600` — target **read/attribute-cache** behavior. But npm install is **write- and create-dominated**: `mkdir`, `open(O_CREAT)`, `write`, `rename`, `symlink`. Each of those is a **synchronous COMMIT/metadata round-trip that the NFS client cannot cache away** — the protocol requires the server to acknowledge the create before npm proceeds. Larger `rsize/wsize` help big sequential reads, not thousands of ~2 KB file creates; attribute caching helps repeated `stat` of the *same* file, which npm barely does. So the per-file latency wall stays exactly where it was. (Note: `nconnect` is silently ignored under `-o tls`/stunnel — a single socket — so it cannot parallelize the round-trips either.)

- **JuiceFS: mount tuning is transformative (−76%, 7m12s → 1m43s).** JuiceFS is a FUSE filesystem where metadata lives in Redis and data lives in S3 objects. In **default** mode every file create is a synchronous Redis metadata txn **plus** an S3 object PUT — that double synchronous path is why default JuiceFS is the slowest of all. Turning on **`--writeback`** makes data writes **asynchronous**: npm's writes land in a local on-disk staging buffer and return immediately, while JuiceFS flushes to S3 in the background. Combined with entry/attr/dir caches (300 s) and a large local cache (10 GB) + write buffer (1 GB), the whole install runs at near-local-disk speed for the duration and even **beats both NFS stores** — because the S3 latency is taken off the critical path. The trade-off: `--writeback` weakens durability (unflushed writes are lost if the client crashes before background upload), which is acceptable for a rebuildable node_modules but not for primary data.

**Bottom line:** For npm-install-style metadata-heavy small-file workloads, generic NFS mount options buy you nothing on EFS or S3 Files — the wall is per-create synchronous round-trip latency, which those knobs don't touch. Only a filesystem that can **defer/batch the writes off the critical path** (JuiceFS `--writeback`) gives a real speedup, and it can even overtake NFS. Nothing comes close to local EBS (13 s), which serializes all of this against local NVMe with no network round-trip at all — ~17× faster than the best network result and ~33× faster than JuiceFS default.

## Cross-reference
See [`kernel-untar-bench-4way`](../kernel-untar-bench-4way/) for the `tar xf` (kernel source, ~101k files) and `git clone` (nixpkgs, ~92k files) baselines on the same four backends, plus a monthly cost comparison. The pattern is consistent: single-threaded small-file work is dominated by per-file metadata latency on every network store; only write-deferral (JuiceFS writeback) or going local (EBS) changes the outcome.
