#!/usr/bin/env python3
"""Join writer CSV(s) (path,target_ts,start_ts,done_ts) with detector seen.csv (path,seen_ts).
usage: analyze.py <tier_name> <out_dir> <seen.csv> <writer.csv> [writer.csv ...]
Outputs: <out>/<tier>_summary.json, <tier>_per_sec.csv (write second -> files written, p50/max lag),
         <tier>_lag.png (lag vs write time), <tier>_vis.png (cumulative written vs visible)
"""
import sys, json, csv
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
tier, out, seenf, wfs = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
seen = {}
for line in open(seenf):
    p, t = line.strip().rsplit(",", 1)
    seen.setdefault(p, float(t))
W = []
for wf in wfs:
    for r in csv.DictReader(open(wf)):
        W.append((r["path"], float(r["target_ts"]), float(r["start_ts"]), float(r["done_ts"])))
W.sort(key=lambda x: x[3])
done = np.array([w[3] for w in W]); tgt = np.array([w[1] for w in W])
lag = np.array([seen[w[0]] - w[3] if w[0] in seen else np.nan for w in W])
missing = int(np.isnan(lag).sum())
t0 = int(min(tgt)); dur = int(np.ceil(done.max() - t0))  # actual write window (writer may fall behind schedule)
in_window = done <= t0 + dur
sec = np.floor(done - t0).astype(int)
cnt = np.bincount(sec[in_window], minlength=dur)[:dur]
sched_s = int(max(tgt)) - t0 + 1  # schedule seconds actually covered
seen_ts = np.array([seen[w[0]] for w in W if w[0] in seen])
pct = lambda q: float(np.nanpercentile(lag, q))
S = dict(tier=tier, files_written=len(W), files_seen=len(W) - missing, missing=missing,
         target_rate=int(tier.replace("rate", "")), write_window_s=dur, schedule_covered_s=sched_s,
         actual_rate_avg=round(len(W) / (done.max() - t0), 1),
         per_sec_min=int(cnt[5:-5].min()) if dur > 10 else int(cnt.min()),
         per_sec_p50=float(np.median(cnt[5:-5])) if dur > 10 else float(np.median(cnt)),
         per_sec_max=int(cnt.max()),
         gib=round(len(W) / 1024, 2),
         write_first=float(done.min()), write_last=float(done.max()),
         seen_last=float(seen_ts.max()),
         all_visible_after_last_write_s=round(float(seen_ts.max() - done.max()), 1),
         lag_min=round(float(np.nanmin(lag)), 1), lag_p50=round(pct(50), 1), lag_p90=round(pct(90), 1),
         lag_p99=round(pct(99), 1), lag_max=round(float(np.nanmax(lag)), 1), lag_mean=round(float(np.nanmean(lag)), 1),
         write_svc_p50_ms=round(float(np.median(done - np.array([w[2] for w in W]))) * 1000, 1),
         write_behind_target_p99_s=round(float(np.percentile(np.array([w[2] for w in W]) - tgt, 99)), 2))
# visibility "batches": distinct clusters of seen_ts (gap > 30s)
st = np.sort(seen_ts); gaps = np.where(np.diff(st) > 30)[0]
batch_starts = [float(st[0])] + [float(st[i + 1]) for i in gaps]
S["visibility_batches"] = len(batch_starts)
S["batch_start_offsets_s"] = [round(b - t0, 1) for b in batch_starts]
S["batch_intervals_s"] = [round(b - a, 1) for a, b in zip(batch_starts, batch_starts[1:])]
json.dump(S, open(f"{out}/{tier}_summary.json", "w"), indent=1)
print(json.dumps(S, indent=1))
with open(f"{out}/{tier}_per_sec.csv", "w") as f:
    f.write("sec_offset,files_done,lag_p50_s,lag_max_s\n")
    for s in range(dur):
        m = sec == s; l = lag[m]
        f.write(f"{s},{int(m.sum())},{np.nanmedian(l) if m.any() else ''},{np.nanmax(l) if m.any() else ''}\n")
fig, ax = plt.subplots(figsize=(11, 4.5))
step = max(1, len(W) // 60000)
ax.scatter((done[::step] - t0) / 60, lag[::step] / 60, s=1)
ax.set_xlabel("write done time (min since tier start)"); ax.set_ylabel("replication lag (min)")
ax.set_title(f"EFS Tokyo->Singapore replication lag, {tier} (1 MiB files)"); ax.grid(alpha=.3)
fig.tight_layout(); fig.savefig(f"{out}/{tier}_lag.png", dpi=110)
fig, ax = plt.subplots(figsize=(11, 4.5))
ax.plot((done - t0) / 60, np.arange(1, len(done) + 1), label="written (Tokyo)")
ax.plot((st - t0) / 60, np.arange(1, len(st) + 1), label="visible (Singapore)")
ax.set_xlabel("min since tier start"); ax.set_ylabel("cumulative files"); ax.legend(); ax.grid(alpha=.3)
ax.set_title(f"Cumulative written vs visible, {tier}")
fig.tight_layout(); fig.savefig(f"{out}/{tier}_vis.png", dpi=110)
