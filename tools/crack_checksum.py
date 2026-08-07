#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crack_checksum.py - efficient sweep to identify the 'flags' low-24 checksum.
Strategy: test the catalog on the SMALL 'user' partition first (~19MB),
collect candidates matching 0x008430, then verify each on 'rootfs'.
ASCII-only output (also written to build/crack_result.txt) to avoid
Windows console encoding crashes.
"""
import struct, zlib, sys, time

F = r"F:\Satelite\Spider VIP\SPIDER-VIP_v1.00.92_20260507.mupg"
OUT = r"G:\Spider-VIP-Firmware-Project\build\crack_result.txt"

# (name, img_len, file_off, part_size, target_low24)
T = {
    "user":   (0x0120E522, 0x1E7A8992, 0x7D000000, 0x008430),
    "rootfs": (0x1D5699FC, 0x0123EF96, 0x49000000, 0x0FD868),
}

log_lines = []
def log(s):
    print(s, flush=True)
    log_lines.append(s)

def read_part(name):
    il, off, ps, tgt = T[name]
    with open(F, "rb") as f:
        f.seek(off)
        return f.read(il)

# ---- parametric CRC (table based) ----
def reflect(x, n):
    r = 0
    for i in range(n):
        if x & (1 << i):
            r |= 1 << (n - 1 - i)
    return r

def make_crc(width, poly, init, refin, refout, xorout):
    topbit = 1 << (width - 1)
    mask = (1 << width) - 1
    table = []
    for b in range(256):
        c = (reflect(b, 8) if refin else b) << (width - 8)
        for _ in range(8):
            c = ((c << 1) ^ poly) if (c & topbit) else (c << 1)
        table.append(c & mask)
    sh = width - 8
    def crc(buf):
        c = init
        tb = table
        for byte in buf:
            c = ((c << 8) ^ tb[((c >> sh) ^ byte) & 0xFF]) & mask
        if refout:
            c = reflect(c, width)
        return c ^ xorout
    return crc

CRC_DEFS = [
    ("CRC24/OPENPGP", 24, 0x864CFB, 0xB704CE, False, False, 0),
    ("CRC24/LTE-A",   24, 0x864CFB, 0x000000, False, False, 0),
    ("CRC24/LTE-B",   24, 0x800063, 0x000000, False, False, 0),
    ("CRC24/OS-9",    24, 0x800063, 0xFFFFFF, False, False, 0xFFFFFF),
    ("CRC24/BLE",     24, 0x00065B, 0x555555, True,  True,  0),
    ("CRC24/FLEXRAY-A",24,0x5D6DCB, 0xFEDCBA, False, False, 0),
    ("CRC24/FLEXRAY-B",24,0x5D6DCB, 0xABCDEF, False, False, 0),
    ("CRC24/refl0",   24, 0x864CFB, 0x000000, True,  True,  0),
    ("CRC24/initFFF", 24, 0x864CFB, 0xFFFFFF, False, False, 0),
    ("CRC16/CCITT-F", 16, 0x1021, 0xFFFF, False, False, 0),
    ("CRC16/XMODEM",  16, 0x1021, 0x0000, False, False, 0),
    ("CRC16/ARC",     16, 0x8005, 0x0000, True,  True,  0),
    ("CRC16/MODBUS",  16, 0x8005, 0xFFFF, True,  True,  0),
]

def crc32_variants(buf):
    c = zlib.crc32(buf) & 0xFFFFFFFF
    return {
        "crc32_low24":   c & 0xFFFFFF,
        "crc32_hi24":    (c >> 8) & 0xFFFFFF,
        "~crc32_low24":  (~c) & 0xFFFFFF,
        "crc32^FFFFFFFF":(c ^ 0xFFFFFFFF) & 0xFFFFFF,
        "adler32_low24": zlib.adler32(buf) & 0xFFFFFF,
    }

def main():
    t0 = time.time()
    log("reading user partition (~19MB)...")
    ubuf = read_part("user")
    utgt = T["user"][3]
    log("user bytes=%d target=0x%06X" % (len(ubuf), utgt))
    log("")

    candidates = []  # list of (label, crc_fn or None, kind)

    log("=== catalog on USER partition ===")
    # fast crc32 variants first
    for lb, val in crc32_variants(ubuf).items():
        hit = (val == utgt)
        log("  %-16s = 0x%06X%s" % (lb, val, "  <== hit" if hit else ""))
        if hit:
            candidates.append((lb, None, "crc32var"))

    # parametric CRCs
    for (lb, w, poly, init, ri, ro, xo) in CRC_DEFS:
        fn = make_crc(w, poly, init, ri, ro, xo)
        val = fn(ubuf) & 0xFFFFFF
        hit = (val == utgt)
        log("  %-16s = 0x%06X%s" % (lb, val, "  <== hit" if hit else ""))
        if hit:
            candidates.append((lb, fn, "crc"))

    log("")
    log("elapsed %.1fs; %d candidate(s) matched USER." % (time.time()-t0, len(candidates)))

    if not candidates:
        log("")
        log("RESULT: no standard checksum in catalog matches the USER target.")
        log("=> The 'flags' field is NOT a common CRC/sum of the partition image,")
        log("   OR it is computed over different data (post-decompression, header,")
        log("   or a vendor-specific algorithm). Cannot recompute it blindly.")
        finish()
        return

    log("")
    log("verifying candidate(s) on ROOTFS (~492MB, may take a while)...")
    rbuf = read_part("rootfs")
    rtgt = T["rootfs"][3]
    for (lb, fn, kind) in candidates:
        if kind == "crc32var":
            val = crc32_variants(rbuf).get(lb, -1)
        else:
            val = fn(rbuf) & 0xFFFFFF
        ok = (val == rtgt)
        log("  %-16s rootfs=0x%06X target=0x%06X %s" %
            (lb, val, rtgt, "<<<<< CONFIRMED ON BOTH!" if ok else "(user-only)"))
    finish()

def finish():
    try:
        with open(OUT, "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines) + "\n")
    except Exception as e:
        print("could not write result file:", e)

if __name__ == "__main__":
    main()
