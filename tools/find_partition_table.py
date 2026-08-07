#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spider VIP - Partition Table Finder
===================================
یافتن جدول پارتیشن در فایل .mupg چیپست HiSilicon Hi3798M V300

روش کار:
  1. استخراج تمام رشته‌های ASCII در ابتدای فایل (اولین 4 مگابایت)
  2. جستجوی نام پارتیشن‌های رایج HiSilicon
  3. تلاش برای تفسیر ساختار جدول پارتیشن (name + offset + size)
"""

import sys
import os
import struct
import re

# نام پارتیشن‌های رایج در ست‌تاپ‌باکس‌های HiSilicon
KNOWN_PARTS = [
    b"fastboot", b"bootargs", b"baseparam", b"logo", b"deviceinfo",
    b"softwareinfo", b"loader", b"kernel", b"recovery", b"rootfs",
    b"userdata", b"data", b"trustedcore", b"stb_env", b"config",
    b"loaderdb", b"page_table", b"fastplay", b"cmm", b"tvdatabase",
    b"upgrade", b"private", b"factory", b"boot", b"system",
]


def extract_strings(data, minlen=4):
    """استخراج رشته‌های ASCII قابل چاپ."""
    result = []
    cur = bytearray()
    start = 0
    for i, b in enumerate(data):
        if 32 <= b <= 126:
            if not cur:
                start = i
            cur.append(b)
        else:
            if len(cur) >= minlen:
                result.append((start, bytes(cur).decode("ascii")))
            cur = bytearray()
    if len(cur) >= minlen:
        result.append((start, bytes(cur).decode("ascii")))
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python find_partition_table.py <path-to-.mupg>")
        sys.exit(1)

    path = sys.argv[1]
    filesize = os.path.getsize(path)

    # خواندن اولین 4 مگابایت (جدول پارتیشن معمولاً در ابتدای فایل است)
    scan_len = min(4 * 1024 * 1024, filesize)
    with open(path, "rb") as f:
        head = f.read(scan_len)

    print("=" * 70)
    print("  یافتن جدول پارتیشن - Spider VIP")
    print("=" * 70)

    # 1) رشته‌های ابتدای فایل (تا 8KB) که معمولاً حاوی جدول پارتیشن‌اند
    print("\n[ رشته‌های ASCII در ابتدای فایل (0x0 - 0x2000) ]")
    strings_head = extract_strings(head[:0x2000], minlen=3)
    for off, s in strings_head:
        print(f"  0x{off:06X}  {s!r}")

    # 2) جستجوی نام پارتیشن‌های شناخته‌شده در کل ناحیه اسکن
    print("\n[ نام پارتیشن‌های شناخته‌شده HiSilicon یافت‌شده ]")
    found_parts = []
    for name in KNOWN_PARTS:
        start = 0
        while True:
            idx = head.find(name, start)
            if idx == -1:
                break
            # بررسی اینکه یک کلمه مستقل باشد (بایت بعدی null یا غیرحرف)
            nb = head[idx + len(name)] if idx + len(name) < len(head) else 0
            if nb == 0 or not (48 <= nb <= 122):
                found_parts.append((idx, name.decode()))
            start = idx + 1
    for off, name in sorted(found_parts):
        # نمایش 48 بایت اطراف برای دیدن ساختار جدول
        ctx = head[off:off + 48]
        hexs = " ".join(f"{b:02X}" for b in ctx[:32])
        print(f"  0x{off:06X}  {name:14}  | {hexs}")

    # 3) تلاش برای شناسایی الگوی جدول پارتیشن
    #    در بسیاری از .mupg ها هر ورودی: نام(char[]) + offset(u32) + size(u32)
    print("\n[ تحلیل احتمالی ساختار جدول پارتیشن ]")
    if found_parts:
        first_off = min(p[0] for p in found_parts)
        last_off = max(p[0] for p in found_parts)
        print(f"  اولین نام پارتیشن @ 0x{first_off:06X}")
        print(f"  آخرین نام پارتیشن @ 0x{last_off:06X}")
        # فاصله بین ورودی‌ها = اندازه هر رکورد
        offs = sorted(set(p[0] for p in found_parts))
        if len(offs) > 1:
            deltas = [offs[i+1] - offs[i] for i in range(len(offs)-1)]
            print(f"  فاصله بین ورودی‌ها (bytes): {deltas}")

    print("\n" + "=" * 70)

    # ذخیره گزارش
    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
    report_path = os.path.join(report_dir, "partition_table.txt")
    with open(report_path, "w", encoding="utf-8") as r:
        r.write("Spider VIP - Partition Table Analysis\n")
        r.write(f"File: {path}\n\n")
        r.write("== ASCII strings @ start (0x0-0x2000) ==\n")
        for off, s in strings_head:
            r.write(f"0x{off:06X}  {s!r}\n")
        r.write("\n== Known partition names ==\n")
        for off, name in sorted(found_parts):
            ctx = head[off:off + 48]
            hexs = " ".join(f"{b:02X}" for b in ctx[:32])
            r.write(f"0x{off:06X}  {name:14}  | {hexs}\n")
    print(f"گزارش ذخیره شد: {report_path}")


if __name__ == "__main__":
    main()
