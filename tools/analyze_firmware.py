#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spider VIP Firmware Analyzer
============================
تحلیلگر ساختار فایل فریمویر رسیور Spider VIP (چیپست HiSilicon Hi3798M V300)

این اسکریپت فایل .mupg را اسکن کرده و ساختار آن را شناسایی می‌کند:
  - هدر اصلی فایل
  - جدول پارتیشن‌ها
  - شناسایی فایل‌سیستم‌ها (UBI, SquashFS, ext, cramfs, ...)
  - نقاط شروع/پایان هر بخش (offset / size)

استفاده:
    python analyze_firmware.py "F:\\Satelite\\Spider VIP\\SPIDER-VIP_v1.00.92_20260507.mupg"
"""

import sys
import os
import struct

# ---------------------------------------------------------------------------
# امضاهای شناخته‌شده (Magic Signatures) برای فایل‌سیستم‌ها و فرمت‌های رایج فریمویر
# ---------------------------------------------------------------------------
MAGICS = [
    (b"UBI#",                     "UBI volume header"),
    (b"UBI!",                     "UBIFS superblock / UBI erase-block"),
    (b"hsqs",                     "SquashFS (little-endian)"),
    (b"sqsh",                     "SquashFS (big-endian)"),
    (b"\x28\xcd\x3d\x45",         "cramfs (little-endian)"),
    (b"\x45\x3d\xcd\x28",         "cramfs (big-endian)"),
    (b"\x1f\x8b\x08",             "gzip stream"),
    (b"\x42\x5a\x68",             "bzip2 stream"),
    (b"\xfd\x37\x7a\x58\x5a\x00", "xz stream"),
    (b"\x5d\x00\x00",             "lzma stream"),
    (b"\x04\x22\x4d\x18",         "lz4 frame"),
    (b"\x27\x05\x19\x56",         "uImage (U-Boot legacy)"),
    (b"\xd0\x0d\xfe\xed",         "FDT / Device Tree Blob (DTB)"),
    (b"ANDROID!",                 "Android boot image"),
    (b"\x53\xef",                 "ext2/3/4 superblock magic (@0x438)"),
    (b"YAFFS",                    "YAFFS filesystem"),
    (b"\x85\x19",                 "JFFS2 node (little-endian)"),
    (b"\x19\x85",                 "JFFS2 node (big-endian)"),
    (b"PK\x03\x04",               "ZIP / JAR archive"),
    (b"\x7fELF",                  "ELF executable/binary"),
    (b"logo",                     "possible logo/boot image marker"),
]

CHUNK = 8 * 1024 * 1024  # 8 MB خواندن هر بار


def read_header(f):
    """خواندن و تفسیر هدر اصلی فایل .mupg (بر اساس تحلیل hex dump)."""
    f.seek(0)
    hdr = f.read(0x60)

    def cstr(b):
        return b.split(b"\x00")[0].decode("ascii", errors="replace")

    info = {}
    info["upgrade_type"]  = cstr(hdr[0x04:0x08])   # مثال: all
    info["product"]       = cstr(hdr[0x08:0x18])   # SPIDER_VIP
    info["base_version"]  = cstr(hdr[0x1C:0x24])   # 1.00.00
    info["fw_version"]    = cstr(hdr[0x28:0x30])   # 1.00.92
    info["chipset"]       = cstr(hdr[0x34:0x40])   # 3798MV300
    info["ddr"]           = cstr(hdr[0x40:0x44]) + " " + cstr(hdr[0x44:0x48])
    info["flash"]         = cstr(hdr[0x48:0x4C]) + " " + cstr(hdr[0x4C:0x50])
    info["checksum_raw"]  = hdr[0x50:0x54].hex().upper()
    return info


def scan_signatures(f, filesize):
    """اسکن کل فایل برای یافتن امضاهای فایل‌سیستم/فشرده‌سازی."""
    hits = []
    overlap = 16
    pos = 0
    tail = b""
    f.seek(0)
    while pos < filesize:
        data = f.read(CHUNK)
        if not data:
            break
        buf = tail + data
        base = pos - len(tail)
        for magic, name in MAGICS:
            start = 0
            while True:
                idx = buf.find(magic, start)
                if idx == -1:
                    break
                abs_off = base + idx
                hits.append((abs_off, magic, name))
                start = idx + 1
        tail = buf[-overlap:]
        pos += len(data)
        # نمایش پیشرفت
        pct = (pos / filesize) * 100
        sys.stdout.write(f"\r  اسکن: {pct:5.1f}%  ({pos:,}/{filesize:,} bytes)")
        sys.stdout.flush()
    print()
    return hits


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_firmware.py <path-to-.mupg>")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"[!] فایل پیدا نشد: {path}")
        sys.exit(1)

    filesize = os.path.getsize(path)
    print("=" * 70)
    print("  Spider VIP Firmware Analyzer")
    print("=" * 70)
    print(f"  فایل : {path}")
    print(f"  حجم  : {filesize:,} bytes ({filesize/1024/1024:.1f} MB)")
    print("-" * 70)

    with open(path, "rb") as f:
        # 1) هدر
        info = read_header(f)
        print("  [ هدر اصلی فایل ]")
        for k, v in info.items():
            print(f"    {k:14}: {v}")
        print("-" * 70)

        # 2) اسکن امضاها
        print("  [ اسکن امضاهای فایل‌سیستم/فشرده‌سازی ]")
        hits = scan_signatures(f, filesize)

    print("-" * 70)
    print(f"  تعداد کل تطبیق‌ها: {len(hits)}")
    print("-" * 70)

    # خلاصه بر اساس نوع
    summary = {}
    for off, magic, name in hits:
        summary.setdefault(name, []).append(off)

    print("  [ خلاصه بر اساس نوع ]")
    for name, offs in sorted(summary.items(), key=lambda x: len(x[1]), reverse=True):
        first = offs[0]
        print(f"    {name:40}  count={len(offs):6}  first@0x{first:08X}")
    print("-" * 70)

    # نوشتن گزارش کامل
    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, "signature_map.txt")
    with open(report_path, "w", encoding="utf-8") as r:
        r.write("Spider VIP Firmware - Signature Map\n")
        r.write(f"File: {path}\n")
        r.write(f"Size: {filesize:,} bytes\n\n")
        r.write("== Header ==\n")
        for k, v in info.items():
            r.write(f"{k:14}: {v}\n")
        r.write("\n== All signature hits (offset : type) ==\n")
        for off, magic, name in sorted(hits):
            r.write(f"0x{off:010X}  {name}\n")
    print(f"  گزارش کامل ذخیره شد: {report_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
