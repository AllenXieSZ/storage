#!/usr/bin/env python3
# ssmrun.py <instance-id> <local-script-or-command-file>
# Sends the file contents as a shell script via SSM, waits, prints stdout.
import sys, json, time, subprocess, base64

iid = sys.argv[1]
path = sys.argv[2]
with open(path) as f:
    script = f.read()

# base64-wrap to avoid quoting issues
b64 = base64.b64encode(script.encode()).decode()
cmd = f"echo {b64} | base64 -d > /tmp/_ssm_run.sh && bash /tmp/_ssm_run.sh"

params = json.dumps({"commands": [cmd]})
out = subprocess.run([
    "aws","ssm","send-command","--instance-ids",iid,
    "--document-name","AWS-RunShellScript",
    "--parameters",params,"--region","us-east-2",
    "--query","Command.CommandId","--output","text"
], capture_output=True, text=True)
cid = out.stdout.strip()
if not cid or "error" in cid.lower():
    print("SEND_FAIL:", out.stdout, out.stderr); sys.exit(1)

for _ in range(240):
    time.sleep(3)
    r = subprocess.run(["aws","ssm","get-command-invocation","--command-id",cid,
        "--instance-id",iid,"--region","us-east-2","--query","Status","--output","text"],
        capture_output=True, text=True)
    st = r.stdout.strip()
    if st == "Success":
        o = subprocess.run(["aws","ssm","get-command-invocation","--command-id",cid,
            "--instance-id",iid,"--region","us-east-2","--query","StandardOutputContent","--output","text"],
            capture_output=True, text=True)
        print(o.stdout); sys.exit(0)
    if st in ("Failed","Cancelled","TimedOut"):
        e = subprocess.run(["aws","ssm","get-command-invocation","--command-id",cid,
            "--instance-id",iid,"--region","us-east-2","--query","StandardErrorContent","--output","text"],
            capture_output=True, text=True)
        print(f"STATUS={st}\n{e.stdout}"); sys.exit(1)
print("TIMEOUT", cid); sys.exit(1)
