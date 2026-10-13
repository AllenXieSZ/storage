#!/usr/bin/env python3
"""持续读取 Lustre changelog，解析成 JSON Lines，每 N 秒切一个文件到 spool 目录。"""
import json, os, re, select, socket, subprocess, sys, time, gzip

MDT = sys.argv[1]                                # 例如 divrbb4v-MDT0000
SPOOL = os.environ.get("SPOOL", "/var/spool/lustre-changelog")
ROTATE = int(os.environ.get("ROTATE_SEC", "300"))
MAXB = float(os.environ.get("ROTATE_MAX_MB", "0")) * 1024 * 1024   # 0=不按大小切；>0 时压缩前字节数达到即切
HOST = socket.gethostname()
os.makedirs(f"{SPOOL}/ready", exist_ok=True)
KV = re.compile(r"^(t|ef|u|nid|p|s|sp|m|x|j)=(.*)$")

def parse(line):
    tok = line.split()
    if len(tok) < 5 or not tok[0].isdigit():
        return None
    hms, ymd = tok[2], tok[3]                    # 05:55:21.970213014 2026.10.09
    r = {"mdt": MDT, "seq": int(tok[0]), "type": tok[1][2:], "type_code": tok[1],
         "time": f"{ymd.replace('.', '-')}T{hms}Z", "flags": tok[4], "collector": HOST}
    last = None
    for t in tok[5:]:
        m = KV.match(t)
        if m:
            k, v = m.groups(); last = k
            if k == "u":
                uid, _, gid = v.partition(":"); r["uid"], r["gid"] = int(uid), int(gid)
            elif k == "t":  r["target_fid"] = v
            elif k == "p":  r["parent_fid"] = v
            elif k == "s":  r["source_fid"] = v
            elif k == "sp": r["source_parent_fid"] = v
            elif k == "nid": r["client_nid"] = v; r["client_ip"] = v.split("@")[0]
            else: r[k] = v
        elif last == "p":  r["name"] = t           # CREAT/MKDIR 文件名；UNLNK/RMDIR 完整路径；RENME 新名字
        elif last == "sp": r["old_path"] = t       # RENME 原路径
    if r.get("name", "").startswith("/"):
        r["path"] = r.pop("name")
    return r

def new_file():
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    p = f"{SPOOL}/{MDT}_{HOST}_{ts}.jsonl.gz"
    k = 1
    while os.path.exists(p + ".part") or os.path.exists(f"{SPOOL}/ready/{os.path.basename(p)}"):
        p = f"{SPOOL}/{MDT}_{HOST}_{ts}-{k}.jsonl.gz"; k += 1     # 同一秒内按大小切多次时避免重名
    return p, gzip.open(p + ".part", "wt")

def salvage():                                    # 启动时：把上次异常退出留下的 .part 中完整的行转存到 ready/
    import glob, zlib
    for part in glob.glob(f"{SPOOL}/{MDT}_*.jsonl.gz.part"):
        try: txt = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(open(part, "rb").read())
        except Exception: txt = b""
        good = [l for l in txt.split(b"\n") if l.endswith(b"}")]
        if good:
            dst = f"{SPOOL}/ready/{os.path.basename(part)[:-len('.jsonl.gz.part')]}-salvaged.jsonl.gz"
            with gzip.open(dst + ".tmp", "wb") as g: g.write(b"\n".join(good) + b"\n")
            os.rename(dst + ".tmp", dst)
        os.remove(part)
salvage()
import signal
STOP = False
def _term(*_):
    global STOP; STOP = True                      # systemctl stop/restart：跑完当前循环后正常切文件退出
signal.signal(signal.SIGTERM, _term)

proc = subprocess.Popen(["lfs", "changelog", "--follow", MDT], stdout=subprocess.PIPE)
fd = proc.stdout.fileno(); buf = b""
path, fh = new_file(); start = time.time(); n = 0; nb = 0; last_flush = 0
def rotate():
    global path, fh, start, n, nb
    fh.close()
    if n: os.rename(path + ".part", f"{SPOOL}/ready/{os.path.basename(path)}")
    else: os.remove(path + ".part")              # 空文件不上传
    path, fh = new_file(); start = time.time(); n = 0; nb = 0
while not STOP:
    ready, _, _ = select.select([fd], [], [], 1.0)
    if ready:                                      # 直接读 fd，避免缓冲区里残留的行要等下一条记录才被处理
        chunk = os.read(fd, 1 << 20)
        if not chunk: break                        # lfs 退出
        *lines, buf = (buf + chunk).split(b"\n")
        for line in lines:
            r = parse(line.decode("utf-8", "replace"))
            if r:
                j = json.dumps(r, ensure_ascii=False) + "\n"; fh.write(j); n += 1; nb += len(j)
                if MAXB and nb >= MAXB: rotate()
    if n and time.time() - last_flush >= 1:        # 每秒 sync flush：进程被 kill -9 时 .part 最多丢 ~1 秒
        fh.flush(); os.fsync(fh.buffer.fileobj.fileno()); last_flush = time.time()
    if time.time() - start >= ROTATE:
        rotate()
rotate(); fh.close(); os.remove(path + ".part")
if STOP: proc.terminate(); sys.exit(0)
sys.exit(proc.wait() or 1)
