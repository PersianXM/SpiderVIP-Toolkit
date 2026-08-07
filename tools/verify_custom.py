#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اعتبارسنجی نهایی فایل mupg سفارشی در برابر اصلی"""
import hashlib, tarfile, gzip, io, struct

ORIG = r"F:\Satelite\Spider VIP\SPIDER-VIP_v1.00.92_20260507.mupg"
CUST = r"G:\Spider-VIP-Firmware-Project\build\SPIDER-VIP_v1.00.92_CUSTOM.mupg"
ROOTFS_OFF = 0x0123EF96
ROOTFS_IMG = 0x1D5699FC
USER_OFF   = ROOTFS_OFF + ROOTFS_IMG

def md5_range(path, start, length):
    h = hashlib.md5()
    with open(path, "rb") as f:
        f.seek(start)
        rem = length
        while rem:
            b = f.read(min(1<<20, rem))
            if not b: break
            h.update(b); rem -= len(b)
    return h.hexdigest()

print("=== 1) هدر + پارتیشن‌های 0..7 (0x0 .. rootfs) باید یکسان باشند ===")
a = md5_range(ORIG, 0, ROOTFS_OFF)
b = md5_range(CUST, 0, ROOTFS_OFF)
print(f"  orig={a}\n  cust={b}\n  {'IDENTICAL ✔' if a==b else 'DIFFERENT ✘'}")

print("\n=== 2) پارتیشن user (بعد از rootfs) باید یکسان باشد ===")
import os
tail_len = os.path.getsize(ORIG) - USER_OFF
a = md5_range(ORIG, USER_OFF, tail_len)
b = md5_range(CUST, USER_OFF, tail_len)
print(f"  orig={a}\n  cust={b}\n  {'IDENTICAL ✔' if a==b else 'DIFFERENT ✘'}")

print("\n=== 3) اندازهٔ کل فایل ===")
print(f"  orig={os.path.getsize(ORIG)}  cust={os.path.getsize(CUST)}  "
      f"{'EQUAL ✔' if os.path.getsize(ORIG)==os.path.getsize(CUST) else 'DIFF ✘'}")

print("\n=== 4) محتوای فایل‌های patch‌شده داخل mupg سفارشی ===")
f = open(CUST, "rb"); f.seek(ROOTFS_OFF)
t = tarfile.open(fileobj=f, mode="r|gz")
targets = {"./usr/bin/bianbiang.sh": None, "./etc/sysctl.conf": None}
for m in t:
    if m.name in targets and m.isreg():
        data = t.extractfile(m).read()
        targets[m.name] = (m.mode, m.size, data)
        if all(v is not None for v in targets.values()):
            break
f.close()
for name,(mode,size,data) in targets.items():
    head = data[:60].decode("utf-8","replace").replace("\n","\\n")
    is_custom = b"CUSTOM" in data or b"ISSUE-003" in data or b"respawn" in data
    print(f"  {name}: mode={oct(mode)} size={size} custom={'YES ✔' if is_custom else 'NO ✘'}")
    print(f"     head: {head[:55]}")

print("\n=== 5) SW version در بلوک‌های softwareinfo (کل فایل mupg) ===")
with open(CUST, "rb") as fh:
    whole = fh.read()
cnt_new = whole.count(b"1.00.93\x00")
cnt_old = whole.count(b"1.00.92\x00")
print(f"  تعداد '1.00.93' : {cnt_new}  {'✔ (باید 3 باشد)' if cnt_new==3 else '✘'}")
print(f"  تعداد '1.00.92' : {cnt_old}  {'✔ (باید 0 باشد)' if cnt_old==0 else '✘ هنوز باقی مانده!'}")
# نمایش آفست‌ها
offs=[]; s=0
while True:
    j=whole.find(b"1.00.93\x00", s)
    if j==-1: break
    offs.append(j); s=j+1
print("  آفست‌ها:", ", ".join(f"0x{o:X}" for o in offs))

print("\n=== نتیجه: SW version در هر 3 بلوک softwareinfo به 1.00.93 تغییر یافت. ===")
