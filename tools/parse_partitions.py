#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spider VIP - Partition Table Parser (نسخه اصلاح‌شده با تشخیص خودکار)
===================================================================
رمزگشایی کامل جدول پارتیشن فایل .mupg چیپست HiSilicon Hi3798M V300

ساختار هر ورودی جدول پارتیشن (36 بایت):
  offset  0..19  : نام پارتیشن (ASCII, null-padded) - 20 بایت
  offset 20..23  : partition_size   (Big-Endian u32) - اندازه رزرو شده روی فلش
  offset 24..27  : image_length     (Big-Endian u32) - طول واقعی داده image
  offset 28..31  : flash_offset     (Big-Endian u32) - آدرس شروع روی NAND/eMMC
  offset 32..35  : flags/reserved   (Big-Endian u32)
"""

import sys
import os
import struct

ENTRY_SIZE = 36
MAX_ENTRIES = 32

KNOWN_FIRST = [b"fastboot", b"boot", b"loader"]


def human(n):
    x = float(n)
    for unit in ["B", "KB", "MB", "GB"]:
        if x < 1024:
            return f"{int(n)}{unit}" if unit == "B" else f"{x:.1f}{unit}"
        x /= 1024
    return f"{x:.1f}TB"


def find_table_start(f, filesize):
    """یافتن آدرس شروع جدول پارتیشن با جستجوی نام اولین پارتیشن نزدیک 0x800."""
    f.seek(0)
    head = f.read(min(0x4000, filesize))
    idx = head.find(b"fastboot")
    if idx == -1:
        idx = head.find(b"boot")
    return idx if idx != -1 else 0x800


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
        # شرط توقف: نام خالی یا نامعتبر
        if not name or not all(32 <= b <= 126 or b == 0 for b in namebytes):
            break
        part_size, img_len, flash_off, flags = struct.unpack(">IIII", rec[20:36])
        # partition_size معتبر باید غیرصفر و کوچکتر از فلش (8GB) باشد
        if part_size == 0 or part_size > 0x200000000:
            break
        entries.append({
            "index": i,
            "name": name,
            "part_size": part_size,
            "img_len": img_len,
            "flash_off": flash_off,
            "flags": flags,
        })
    return entries


def main():
    if len(sys.argv) < 2:
        print("Usage: python parse_partitions.py <path-to-.mupg>")
        sys.exit(1)

    path = sys.argv[1]
    filesize = os.path.getsize(path)

    with open(path, "rb") as f:
        table_off = find_table_start(f, filesize)
        entries = parse_table(f, table_off)

    print("=" * 104)
    print("  Spider VIP - جدول پارتیشن رمزگشایی‌شده")
    print("=" * 104)
    print(f"  فایل: {os.path.basename(path)}   (حجم: {human(filesize)})")
    print(f"  جدول @ 0x{table_off:X}  | تعداد پارتیشن: {len(entries)}")
    print("-" * 104)
    print(f"  {'#':>2}  {'name':<12} {'part_size':>18} {'img_len(data)':>18} {'flash_offset':>16} {'flags':>10}")
    print("-" * 104)

    total_img = 0
    for e in entries:
        total_img += e["img_len"]
        print(f"  {e['index']:>2}  {e['name']:<12} "
              f"{human(e['part_size']):>8} (0x{e['part_size']:08X})  "
              f"{human(e['img_len']):>8} (0x{e['img_len']:08X})  "
              f"0x{e['flash_off']:010X}  0x{e['flags']:08X}")
    print("-" * 104)
    print(f"  مجموع طول داده image ها: {human(total_img)} (0x{total_img:X})")
    print(f"  حجم فایل کل            : {human(filesize)}")
    print("=" * 104)

    # ذخیره گزارش
    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, "partition_layout.txt")
    with open(report_path, "w", encoding="utf-8") as r:
        r.write("Spider VIP - Decoded Partition Table\n")
        r.write(f"File: {path}  ({filesize:,} bytes)\n")
        r.write(f"Table @ 0x{table_off:X}, entry size {ENTRY_SIZE}, count {len(entries)}\n\n")
        r.write(f"{'#':>2}  {'name':<12} {'part_size':>12} {'img_len':>12} {'flash_off':>14} {'flags':>10}\n")
        r.write("-" * 76 + "\n")
        for e in entries:
            r.write(f"{e['index']:>2}  {e['name']:<12} "
                    f"0x{e['part_size']:08X} 0x{e['img_len']:08X} "
                    f"0x{e['flash_off']:010X} 0x{e['flags']:08X}  "
                    f"# {human(e['part_size'])} part / {human(e['img_len'])} data @ flash 0x{e['flash_off']:X}\n")
    print(f"گزارش ذخیره شد: {report_path}")


if __name__ == "__main__":
    main()
