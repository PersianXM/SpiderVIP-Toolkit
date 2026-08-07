#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""جستجوی جامع رشتهٔ 1.00.92 در کل فایل mupg + شناسایی پارتیشن هر مورد"""
import struct

F = r"F:\Satelite\Spider VIP\SPIDER-VIP_v1.00.92_20260507.mupg"
DATA_START = 0x1000

# جدول پارتیشن‌ها را از هدر بخوانیم (نام،part_size،img_len،flash،flags)
with open(F, "rb") as f:
    data = f.read()

print(f"filesize = {len(data)} (0x{len(data):X})")

# استخراج جدول پارتیشن از ناحیهٔ 0x400..0x1000 (رکوردهای 36 بایتی: 20 نام + 4*u32)
# نام‌ها را با اسکن ASCII پیدا می‌کنیم
parts = []
i = 0x400
# نگاشت offset فایل هر پارتیشن را با شمارش تجمعی img_len از DATA_START می‌سازیم
known = ["logo","fastplay","kernel","rootfs","user","deviceinfo","apploader","mainapp"]
# به‌جای حدس، رکوردها را با جستجوی نام‌های محتمل پیدا می‌کنیم
name_offsets = []
for nm in [b"logo",b"kernel",b"rootfs",b"user",b"deviceinfo",b"fastplay",
           b"baseparam",b"pqparam",b"loader",b"fastboot",b"bootargs",b"softwareinfo",
           b"version",b"mainapp",b"apploader"]:
    idx = data.find(nm+b"\x00", 0x400, 0x1000)
    if idx != -1:
        rec = data[idx:idx+36]
        try:
            a,b_,c,d = struct.unpack(">IIII", rec[20:36])
            name_offsets.append((idx, nm.decode(), a,b_,c,d))
        except: pass
name_offsets.sort()
print("\n=== رکوردهای جدول پارتیشن یافت‌شده ===")
cum = DATA_START
for idx,nm,a,b_,c,d in name_offsets:
    print(f"  @0x{idx:X} {nm:12} f1=0x{a:X} img=0x{b_:X} f3=0x{c:X} flags=0x{d:08X}")

# آفست فایل هر پارتیشن (تجمعی بر اساس img_len به ترتیب ظاهر در جدول)
print("\n=== آفست فایل پارتیشن‌ها (تجمعی) ===")
cum = DATA_START
layout = []
for idx,nm,a,b_,c,d in name_offsets:
    layout.append((nm, cum, b_))
    print(f"  {nm:12} file_off=0x{cum:X} .. 0x{cum+b_:X}  (img=0x{b_:X})")
    cum += b_

# جستجوی همهٔ 1.00.92 و 1.00.93 در کل فایل
def scan(pat):
    res=[]; s=0
    while True:
        j = data.find(pat, s)
        if j==-1: break
        res.append(j); s=j+1
    return res

for pat in [b"1.00.92", b"1.00.93"]:
    hits = scan(pat)
    print(f"\n=== '{pat.decode()}' : {len(hits)} مورد ===")
    for off in hits:
        # کدام پارتیشن؟
        where="?"
        for nm,st,ln in layout:
            if st <= off < st+ln:
                where=f"{nm}(+0x{off-st:X})"; break
        if off < DATA_START: where="HEADER"
        ctx = data[max(0,off-24):off+16]
        ctx_s = ''.join(chr(x) if 32<=x<=126 else '.' for x in ctx)
        print(f"  0x{off:08X} [{where:16}] {ctx_s}")
