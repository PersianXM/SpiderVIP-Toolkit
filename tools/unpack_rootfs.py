#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spider VIP - rootfs unpacker
============================
مرحله 1: باز کردن لایه gzip روی rootfs.bin
مرحله 2: تشخیص نوع فایل‌سیستم داخلی (cramfs/squashfs/ext/tar/cpio)
مرحله 3: اگر tar/cpio بود، استخراج کامل درخت فایل‌ها

خروجی: rootfs.unpacked (فایل‌سیستم خام) در پوشه extracted
"""

import sys
import os
import gzip
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRACTED = os.path.join(os.path.dirname(HERE), "extracted")


def human(n):
    x = float(n)
    for u in ["B", "KB", "MB", "GB"]:
        if x < 1024:
            return f"{int(n)}{u}" if u == "B" else f"{x:.1f}{u}"
        x /= 1024
    return f"{x:.1f}TB"


def gunzip(src, dst):
    print(f"  باز کردن gzip: {os.path.basename(src)} ...")
    total = 0
    with gzip.open(src, "rb") as f_in, open(dst, "wb") as f_out:
        while True:
            chunk = f_in.read(8 * 1024 * 1024)
            if not chunk:
                break
            f_out.write(chunk)
            total += len(chunk)
            sys.stdout.write(f"\r    نوشته‌شده: {human(total)}")
            sys.stdout.flush()
    print()
    return total


def detect_fs(path):
    with open(path, "rb") as f:
        head = f.read(1024)
    # امضاها
    if head[:4] == b"hsqs":
        return "squashfs-le"
    if head[:4] == b"sqsh":
        return "squashfs-be"
    if head[:4] == b"\x28\xcd\x3d\x45":
        return "cramfs-le"
    if head[:4] == b"\x45\x3d\xcd\x28":
        return "cramfs-be"
    if head[257:262] == b"ustar":
        return "tar"
    if head[:6] in (b"070701", b"070702", b"070707"):
        return "cpio"
    if head[:4] == b"UBI#":
        return "ubi"
    # ext superblock @ 0x438
    with open(path, "rb") as f:
        f.seek(0x438)
        if f.read(2) == b"\x53\xef":
            return "ext"
    return "unknown"


def main():
    src = os.path.join(EXTRACTED, "rootfs.bin")
    if not os.path.isfile(src):
        print(f"[!] یافت نشد: {src}")
        sys.exit(1)

    print("=" * 70)
    print("  باز کردن rootfs")
    print("=" * 70)
    dst = os.path.join(EXTRACTED, "rootfs.unpacked")
    size = gunzip(src, dst)
    print(f"  حجم پس از decompress: {human(size)}")

    fs = detect_fs(dst)
    print(f"  نوع فایل‌سیستم داخلی: {fs}")

    # نمایش هدر
    with open(dst, "rb") as f:
        head = f.read(64)
    hexs = " ".join(f"{b:02X}" for b in head[:32])
    print(f"  هدر: {hexs}")
    print("=" * 70)

    # اگر squashfs بود، اطلاعات superblock را بخوان
    if fs.startswith("squashfs"):
        with open(dst, "rb") as f:
            sb = f.read(96)
        # squashfs 4.0 superblock (little-endian)
        magic, inodes, mkfs_time, block_size, frags, comp, block_log = \
            struct.unpack("<IIIIIHH", sb[0:24])
        comp_names = {1: "gzip", 2: "lzma", 3: "lzo", 4: "xz", 5: "lz4", 6: "zstd"}
        print("  [ SquashFS superblock ]")
        print(f"    inode count : {inodes}")
        print(f"    block size  : {block_size}")
        print(f"    fragments   : {frags}")
        print(f"    compression : {comp_names.get(comp, comp)}")

    print(f"\n  خروجی: {dst}")
    print("  گام بعد: استخراج درخت فایل‌ها بر اساس نوع فایل‌سیستم")


if __name__ == "__main__":
    main()
