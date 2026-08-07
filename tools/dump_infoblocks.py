#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ریختن هگز کامل بلوک‌های اطلاعات نسخه برای درک ساختار"""
F = r"F:\Satelite\Spider VIP\SPIDER-VIP_v1.00.92_20260507.mupg"
with open(F,"rb") as f: data=f.read()

def hexdump(off, length, label):
    print(f"\n===== {label} @0x{off:X} (len {length}) =====")
    for row in range(0, length, 16):
        chunk = data[off+row: off+row+16]
        hexs = ' '.join(f"{b:02X}" for b in chunk)
        asci = ''.join(chr(b) if 32<=b<=126 else '.' for b in chunk)
        print(f"  0x{off+row:08X}  {hexs:<48}  {asci}")

# سه ناحیه: هر کدام کمی قبل از رشته شروع، طول 96
hexdump(0x00000010, 0x60, "HEADER block #1")
hexdump(0x00000420, 0x60, "HEADER block #2 (0x434)")
hexdump(0x001BE308, 0x60, "logo/deviceinfo region (0x1BE31C)")

# مرزهای دقیق پارتیشن logo و deviceinfo برای تعیین محل واقعی 0x1BE31C
print("\nlogo:       0x1286E8 .. 0x1BE6E8")
print("deviceinfo: 0x1BE6E8 .. 0x1BEAE8")
print("0x1BE31C در محدودهٔ:", "logo" if 0x1286E8<=0x1BE31C<0x1BE6E8 else "deviceinfo")
print("فاصله تا انتهای logo:", 0x1BE6E8-0x1BE31C, "بایت")
