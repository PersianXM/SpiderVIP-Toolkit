#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تأیید نگاشت خام + تست CRC-24 و حالت‌های padded"""
import struct, zlib

F = r"F:\Satelite\Spider VIP\SPIDER-VIP_v1.00.92_20260507.mupg"

with open(F,"rb") as f:
    head = f.read(0x1000)

# پیدا کردن آفست دقیق هر رکورد با جستجوی نام
def find_entry(name):
    idx = head.find(name.encode()+b"\x00", 0x800)
    # نام از idx شروع می‌شود؛ 4 فیلد u32 بعد از 20 بایت نام
    rec = head[idx: idx+36]
    part, img, flash, flags = struct.unpack(">IIII", rec[20:36])
    return idx, part, img, flash, flags

for nm in ["rootfs","user"]:
    idx,part,img,flash,flags = find_entry(nm)
    print(f"{nm}: name@0x{idx:X} part=0x{part:X} img=0x{img:X} flash=0x{flash:X} flags=0x{flags:08X}")
    raw = head[idx+20: idx+36]
    print("   raw 16B:", raw.hex())

# CRC-24 (مثل OpenPGP / برخی فرمت‌ها)
def crc24(data, poly=0x864CFB, init=0xB704CE):
    crc = init
    for b in data:
        crc ^= (b << 16)
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= poly
    return crc & 0xFFFFFF

targets = [("rootfs",0x1D5699FC,0x0123EF96,0x0FD868,0x49000000),
           ("user",  0x0120E522,0x1E7A8992,0x008430,0x7D000000)]

with open(F,"rb") as f:
    for name, il, off, target, part in targets:
        f.seek(off); data=f.read(il)
        print(f"\n=== {name} target=0x{target:06X} ===")
        print(f"   crc24(openpgp)      = 0x{crc24(data):06X}")
        print(f"   crc24 init0         = 0x{crc24(data,init=0):06X}")
        # sum بایت روی داده + صفرهای padding تا part_size
        pad = part - il
        s_padded = (sum(data)) & 0xFFFFFF  # صفرها اثری ندارند
        print(f"   sum8 (pad بی‌اثر)    = 0x{s_padded:06X}")
        # sum32 big-endian
        s32be=0
        n=il-(il%4)
        for i in range(0,n,4): s32be+=struct.unpack_from(">I",data,i)[0]
        print(f"   sum32be&0xFFFFFF    = 0x{s32be & 0xFFFFFF:06X}")
        # crc32 با init/xor مختلف
        print(f"   ~crc32&0xFFFFFF     = 0x{(~zlib.crc32(data))&0xFFFFFF:06X}")
