#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spider VIP - Partition Image Extractor
======================================
استخراج image هر پارتیشن از فایل .mupg

کشف مهم:
  داده image ها از offset 0x1000 فایل شروع می‌شوند و پشت سر هم (بدون فاصله)
  به ترتیب جدول پارتیشن با طول img_len هر کدام چیده شده‌اند.
  (تأیید: filesize - sum(img_len) = 0x1000)
"""

import sys
import os
import struct

ENTRY_SIZE = 36
MAX_ENTRIES = 32
DATA_START = 0x1000  # کشف‌شده: image ها از اینجا شروع می‌شوند


def human(n):
    x = float(n)
    for u in ["B", "KB", "MB", "GB"]:
        if x < 1024:
            return f"{int(n)}{u}" if u == "B" else f"{x:.1f}{u}"
        x /= 1024
    return f"{x:.1f}TB"


def find_table_start(f, filesize):
    f.seek(0)
    head = f.read(min(0x4000, filesize))
    idx = head.find(b"fastboot")
    return idx if idx != -1 else 0x805


def parse_table(f, table_off):
    f.seek(table_off)
    raw = f.read(ENTRY_SIZE * MAX_ENTRIES)
    entries = []
    for i in range(MAX_ENTRIES):
        rec = raw[i * ENTRY_SIZE:(i + 1) * ENTRY_SIZE]
        if len(rec) < ENTRY_SIZE:
            break
        namebytes = rec[0:20]
        name = namebytes.split(b"\x00")[0].decode("ascii", errors="replace")
        if not name or not all(32 <= b <= 126 or b == 0 for b in namebytes):
            break
        part_size, img_len, flash_off, flags = struct.unpack(">IIII", rec[20:36])
        if part_size == 0 or part_size > 0x200000000:
            break
        entries.append({"name": name, "part_size": part_size,
                        "img_len": img_len, "flash_off": flash_off, "flags": flags})
    return entries


def detect_type(sample):
    sigs = [
        (b"UBI#", "UBI"), (b"UBI!", "UBI"), (b"hsqs", "SquashFS-LE"),
        (b"sqsh", "SquashFS-BE"), (b"\x27\x05\x19\x56", "uImage"),
        (b"\xd0\x0d\xfe\xed", "DTB"), (b"ANDROID!", "AndroidBoot"),
        (b"\x1f\x8b\x08", "gzip"), (b"\x28\xcd\x3d\x45", "cramfs"),
        (b"\x85\x19", "JFFS2"), (b"BM", "BMP-image"),
        (b"\x89PNG", "PNG-image"), (b"\xff\xd8\xff", "JPEG-image"),
        (b"GIF8", "GIF-image"),
    ]
    for sig, name in sigs:
        if sample.startswith(sig):
            return name
    for sig, name in sigs:
        if sig in sample[:256]:
            return name + "(embedded)"
    return "unknown/raw"


def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_partitions.py <path-to-.mupg> [only_name]")
        sys.exit(1)

    path = sys.argv[1]
    only = sys.argv[2] if len(sys.argv) > 2 else None
    filesize = os.path.getsize(path)

    outdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "extracted")
    os.makedirs(outdir, exist_ok=True)

    with open(path, "rb") as f:
        table_off = find_table_start(f, filesize)
        entries = parse_table(f, table_off)

        cursor = DATA_START
        print("=" * 90)
        print("  استخراج پارتیشن‌ها")
        print("=" * 90)
        print(f"  {'name':<12} {'file_offset':>12} {'img_len':>12}  {'type':<16} خروجی")
        print("-" * 90)
        for e in entries:
            start = cursor
            length = e["img_len"]
            cursor += length
            if only and e["name"] != only:
                continue
            f.seek(start)
            sample = f.read(min(512, length))
            ftype = detect_type(sample)
            outname = f"{e['name']}.bin"
            outpath = os.path.join(outdir, outname)
            # نوشتن فایل به صورت chunk
            f.seek(start)
            remaining = length
            with open(outpath, "wb") as out:
                while remaining > 0:
                    chunk = f.read(min(8 * 1024 * 1024, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
            print(f"  {e['name']:<12} 0x{start:010X} {human(length):>10}  {ftype:<16} {outname}")
        print("-" * 90)
        print(f"  همه در: {outdir}")
        print("=" * 90)


if __name__ == "__main__":
    main()
