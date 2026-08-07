#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تحلیل دقیق هدر/جدول/فیلد اندازه یا checksum فایل mupg"""
import os, struct, zlib, sys

F = r"F:\Satelite\Spider VIP\SPIDER-VIP_v1.00.92_20260507.mupg"
filesize = os.path.getsize(F)

with open(F, "rb") as f:
    head = f.read(0x1000)

print(f"filesize            = {filesize} (0x{filesize:X})")

val50 = struct.unpack(">I", head[0x50:0x54])[0]
print(f"field@0x50 (BE)     = 0x{val50:X} ({val50})")
print(f"filesize - 0x400    = 0x{filesize-0x400:X}")
print(f"filesize - 0x1000   = 0x{filesize-0x1000:X}")
print(f"field@0x50 == filesize-0x400 ? {val50 == filesize-0x400}")
print(f"ascii@0x54..0x5C    = {head[0x54:0x5C]!r}")

# جدول پارتیشن: magic AA BC DE FA @0x800، سپس ورودی‌ها از 0x805
print("\n=== partition table entries (name[20] + 4x u32 BE) ===")
base = 0x805
cursor_file = 0x1000
entries = []
for i in range(12):
    rec = head[base + i*36 : base + i*36 + 36]
    if len(rec) < 36: break
    name = rec[0:20].split(b"\x00")[0].decode("ascii", "replace")
    if not name: break
    part_size, img_len, flash_off, flags = struct.unpack(">IIII", rec[20:36])
    if part_size == 0 or part_size > 0x200000000: break
    entries.append((name, part_size, img_len, flash_off, flags, cursor_file))
    print(f"  [{i}] {name:<12} part=0x{part_size:08X} img=0x{img_len:08X} "
          f"flash=0x{flash_off:08X} flags=0x{flags:08X} file_off=0x{cursor_file:08X}")
    cursor_file += img_len

total_img = sum(e[2] for e in entries)
print(f"\nsum(img_len)        = 0x{total_img:X} ({total_img})")
print(f"0x1000 + sum        = 0x{0x1000+total_img:X}")
print(f"== filesize ? {0x1000+total_img == filesize}")

# آیا flags یک checksm هر پارتیشن است؟ برای پارتیشن‌های کوچک تست کنیم
print("\n=== آیا flags = crc32 یا sum32 image هر پارتیشن است؟ ===")
with open(F, "rb") as f:
    for name, ps, il, fo, flags, foff in entries[:6]:
        f.seek(foff)
        data = f.read(il)
        crc = zlib.crc32(data) & 0xFFFFFFFF
        s32 = sum(data) & 0xFFFFFFFF
        print(f"  {name:<12} flags=0x{flags:08X} crc32=0x{crc:08X} sum32=0x{s32:08X} "
              f"{'CRC!' if crc==flags else ''}{'SUM!' if s32==flags else ''}")
