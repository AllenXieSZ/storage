#!/usr/bin/env python3
"""Generate test files for ONTAP Storage Efficiency experiment. Python 3.7+ compatible.
Uses struct.pack + os.urandom for speed. ~512MB per file."""
import os, sys, time, struct, random, shutil

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/test_data"
os.makedirs(OUT_DIR, exist_ok=True)

FILE_SIZE = 512 * 1024 * 1024  # 512 MB
CHUNK = 4 * 1024 * 1024        # 4 MB write chunks

random.seed(42)
t0 = time.time()

def timed_write(name, desc, gen_fn, total=FILE_SIZE):
    path = os.path.join(OUT_DIR, name)
    print(f"[{time.time()-t0:.0f}s] Generating: {desc}")
    t = time.time()
    with open(path, 'wb') as f:
        written = 0
        while written < total:
            sz = min(CHUNK, total - written)
            f.write(gen_fn(sz))
            written += sz
    mb = os.path.getsize(path) / 1048576
    el = time.time() - t
    print(f"  -> {mb:.0f} MB in {el:.1f}s ({mb/el:.0f} MB/s)")
    return path

# ---- Generators ----

# 1. Dense random (incompressible baseline)
timed_write("01_dense_random_512mb.bin", "Dense random bytes (baseline)",
            lambda sz: os.urandom(sz))

# 2. 50% scattered sparse: use random mask via os.urandom
# Strategy: generate random data, then for each 2-byte pair, if random byte < 128, zero it
def gen_50_scattered(sz):
    data = bytearray(os.urandom(sz))
    mask = os.urandom(sz // 2)  # one byte per FP16 word
    for i in range(len(mask)):
        if mask[i] < 128:  # ~50% probability
            data[i*2] = 0
            data[i*2+1] = 0
    return bytes(data)

timed_write("02_sparse50_scattered_512mb.bin", "50% scattered sparse (non-structured pruning)",
            gen_50_scattered)

# 3. 90% scattered sparse
def gen_90_scattered(sz):
    data = bytearray(os.urandom(sz))
    mask = os.urandom(sz // 2)
    for i in range(len(mask)):
        if mask[i] < 230:  # ~90% probability (230/256 = 0.898)
            data[i*2] = 0
            data[i*2+1] = 0
    return bytes(data)

timed_write("03_sparse90_scattered_512mb.bin", "90% scattered sparse",
            gen_90_scattered)

# 4. 50% contiguous (first half zeros, second half random)
# Simple: write zeros for first half, random for second half
_pos = [0]
def gen_contiguous(sz):
    half = FILE_SIZE // 2
    pos = _pos[0]
    if pos + sz <= half:
        _pos[0] += sz
        return b'\x00' * sz
    elif pos >= half:
        _pos[0] += sz
        return os.urandom(sz)
    else:
        zero_part = half - pos
        rand_part = sz - zero_part
        _pos[0] += sz
        return b'\x00' * zero_part + os.urandom(rand_part)

timed_write("04_sparse50_contiguous_512mb.bin", "50% contiguous sparse (structured pruning)",
            gen_contiguous)

# 5. All zeros
timed_write("05_allzero_512mb.bin", "100% zeros",
            lambda sz: b'\x00' * sz)

# 6. 2:4 semi-structured: every 8 bytes (4 FP16), zero out 2 random FP16 words
def gen_2to4(sz):
    data = bytearray(os.urandom(sz))
    # Process in 8-byte groups
    for i in range(0, sz - 7, 8):
        # Pick 2 of 4 positions to zero (simple deterministic pattern for speed)
        # Use 2 bits from data itself to pick pattern
        pat = data[i] & 0x07  # 8 patterns
        if pat == 0:   z = (0,1)
        elif pat == 1: z = (0,2)
        elif pat == 2: z = (0,3)
        elif pat == 3: z = (1,2)
        elif pat == 4: z = (1,3)
        elif pat == 5: z = (2,3)
        else:          z = (0,3)  # default for 6,7
        for idx in z:
            off = i + idx * 2
            data[off] = 0
            data[off+1] = 0
    return bytes(data)

timed_write("06_semi24_512mb.bin", "2:4 semi-structured sparse",
            gen_2to4)

# 7. INT4 quantized (random packed nibbles = essentially random bytes)
timed_write("07_int4_random_256mb.bin", "INT4 quantized random",
            lambda sz: os.urandom(sz), total=256*1024*1024)

# 8. Duplicate of file 01 for dedup test
print(f"[{time.time()-t0:.0f}s] Copying 01 -> 08 for dedup test")
shutil.copy2(os.path.join(OUT_DIR, "01_dense_random_512mb.bin"),
             os.path.join(OUT_DIR, "08_dedup_copy_of_01.bin"))

print(f"\n=== All done in {time.time()-t0:.0f}s ===")
total_mb = 0
for f in sorted(os.listdir(OUT_DIR)):
    sz = os.path.getsize(os.path.join(OUT_DIR, f))
    total_mb += sz
    print(f"  {f}: {sz/1048576:.0f} MB")
print(f"  TOTAL: {total_mb/1048576:.0f} MB")
