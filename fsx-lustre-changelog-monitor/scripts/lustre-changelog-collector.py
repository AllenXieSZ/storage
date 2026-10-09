#!/usr/bin/env python3
"""持续读取 Lustre changelog，解析成 JSON Lines，每 N 秒切一个文件到 spool 目录。"""
import json, os, re, select, socket, subprocess, sys, time, gzip

MDT = sys.argv[1]                                # 例如 divrbb4v-MDT0000
SPOOL = os.environ.get("SPOOL", "/var/spool/lustre-changelog")
ROTATE = int(os.environ.get("ROTATE_SEC", "300"))
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
    return p, gzip.open(p + ".part", "wt")

proc = subprocess.Popen(["lfs", "changelog", "--follow", MDT], stdout=subprocess.PIPE, text=True, bufsize=1)
path, fh = new_file(); start = time.time(); n = 0
def rotate():
    global path, fh, start, n
    fh.close()
    if n: os.rename(path + ".part", f"{SPOOL}/ready/{os.path.basename(path)}")
    else: os.remove(path + ".part")              # 空文件不上传
    path, fh = new_file(); start = time.time(); n = 0
while True:
    ready, _, _ = select.select([proc.stdout], [], [], 1.0)
    if ready:
        line = proc.stdout.readline()
        if not line: break                         # lfs 退出
        r = parse(line)
        if r: fh.write(json.dumps(r, ensure_ascii=False) + "\n"); n += 1
    if time.time() - start >= ROTATE:
        rotate()
rotate(); fh.close(); os.remove(path + ".part")
sys.exit(proc.wait() or 1)
