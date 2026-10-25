# PHP2Shell PoC RUN_LOG

## 2026-10-25 12:27 UTC — Task Start

### Environment Reconnaissance
- **PHP Version (all 3 instances)**: PHP 8.5.9 (cli) (built Jul 28 2026)
  - **Vulnerable**: fix version is 8.5.12, current 8.5.9 < 8.5.12 ✓
- **SAPI**: php-fpm (NOT mod_php), pm.max_children=200, pm.max_requests=unset
- **Apache**: 2.4.68 mpm_event → proxy_fcgi → php-fpm
- **OpenCart Version**: 4.1.0.4
- **session.upload_progress.enabled**: On (default, vulnerable config)
- **session.upload_progress.cleanup**: On
- **session.save_handler**: files (/var/lib/php/session/)
- **session.serialize_handler**: php
- **memory_limit**: 128M
- **post_max_size**: 8M
- **Instances**:
  - <INSTANCE_1>: ip-10-20-11-97 (AZ a)
  - <INSTANCE_2>: ip-10-20-13-211 (AZ c)
  - <INSTANCE_3>: ip-10-20-12-26 (AZ b)

### Functional Verification (12:27 UTC)
- CloudFront homepage: HTTP 200, 31087 bytes ✓
- Product page (product_id=43): HTTP 200, 32168 bytes ✓
- Cart add: JSON success ✓
- Cart view: MacBook $602.00 ✓
- Payment methods: PayPal Sandbox available ✓

## 12:35 UTC — OOM Exploitation Test (Phase 1)

**Command (ran from instance via SSM, targeting localhost):**
```python
# 800 empty-filename upload fields with 40-deep nesting
# PHP_SESSION_UPLOAD_PROGRESS + PHPSESSID cookie
# Content-Length header (not chunked), total body ~235KB
for i in range(800):
    nesting = "".join(f"[{rand_str(2)}]" for _ in range(40))
    name = f"f{nesting}[{i}]"
    # filename="" → not counted toward max_file_uploads
    # but creates 6 $_FILES entries with nested HashTable expansion
```

**Result: 10/10 HTTP 500 + 10/10 session files created**

Session files at `/var/lib/php/session/sess_<attacker_id>` (all 0 bytes):
```
sess_cmeomw7cl7sdwf6r1g7xzek1d1
sess_n9izhat1afbwls3eqywnwm6v89
sess_5dulud0outnsg5hzzs1vlsy96x
sess_4306newm1v1wkktxu4t1d3vm53
sess_8cb2lx5efn9b7geaaptic9s430
... (10 total)
```

PHP-FPM log: no SIGSEGV, no child death signals. OOM handled as soft memory_limit fatal.
Phase 2 stale probe: 0/10 crashes (FPM terminates crashed workers, fresh workers handle P2).

## 12:39 UTC — Chunked Transfer-Encoding Test

Tried chunked TE to bypass post_max_size (Calif technique).
Result: HTTP 200 — Apache returned `AH01075: Error dispatching request to : (reading input brigade)`.
Chunked approach did not trigger OOM through this proxy configuration.

## 12:41 UTC — Session Data Race Test

Attempted to catch session upload_progress data during slow upload.
Result: Could not capture data before cleanup. session.upload_progress.cleanup=On.

## 12:43 UTC — Mitigation Applied (Instance 1)

```bash
echo "session.upload_progress.enabled = Off" > /etc/php.d/99-php2shell-mitigation.ini
systemctl restart php-fpm
```

Retest: OOM still 5/5 (500), but **session files: 0/5** → mitigation effective for session poisoning vector.

## 12:45 UTC — PHP Upgrade (Instance 1)

```bash
dnf upgrade --releasever=latest -y php8.5*  # 8.5.9 → 8.5.12
rm -f /etc/php.d/99-php2shell-mitigation.ini  # remove mitigation (fix is in code now)
systemctl restart php-fpm
```

Retest on 8.5.12: **0/5 OOM, 5/5 HTTP 200** → FIX VERIFIED.

## 12:49 UTC — PHP Upgrade (Instances 2 & 3)

Both upgraded 8.5.9 → 8.5.12, php-fpm restarted, verified.

## 12:50 UTC — Post-Fix Functional Verification

- Homepage: HTTP 200, 31087 bytes ✓
- Product page: HTTP 200, 32168 bytes ✓
- Cart add: JSON success ✓

## 12:51 UTC — Cleanup

- Removed test session files from all 3 instances
- Removed temporary python scripts from /tmp/
- Environment left running as requested

## Summary

| Stage | OOM (HTTP 500) | Session Files | RCE |
|-------|----------------|---------------|-----|
| Before fix (8.5.9, upload_progress=On) | 10/10 ✗ | 10/10 ✗ | Not achieved (FPM limitation) |
| Mitigation (8.5.9, upload_progress=Off) | 5/5 ✗ | 0/5 ✓ | Blocked |
| After fix (8.5.12, upload_progress=On) | 0/5 ✓ | 5/5 (normal) | N/A (fixed) |
