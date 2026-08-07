#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""بررسی شواهد واقعی مقدار RAM از bootargs/kernel cmdline/baseparam"""
import re
F = r"F:\Satelite\Spider VIP\SPIDER-VIP_v1.00.92_20260507.mupg"
with open(F,"rb") as f: data=f.read()

# آفست‌های پارتیشن‌ها (از اسکن قبلی)
PARTS = {
    "fastboot":   (0x1000,   0xEB800),
    "bootargs":   (0xEC800,  0x10000),
    "baseparam":  (0xFC800,  0x16AC),
    "pqparam":    (0xFDEAC,  0x2A83C),
    "logo":       (0x1286E8, 0x96000),
    "deviceinfo": (0x1BE6E8, 0x400),
    "loader":     (0x1BEAE8, 0xA8C8BB),
    "kernel":     (0xC4B3A3, 0x5F3BF3),
}

def strings(b, minlen=4):
    return re.findall(rb"[\x20-\x7E]{%d,}" % minlen, b)

# 1) دنبال mem= / DDR / اندازهٔ حافظه در bootargs و fastboot و baseparam
print("=== الگوهای مرتبط با RAM در پارتیشن‌های راه‌انداز ===")
patterns = [rb"mem=\S+", rb"ddr\S*", rb"DDR\S*", rb"\d+GB", rb"\d+MB",
            rb"total_mem\S*", rb"memsize\S*", rb"mmz\S*", rb"mem_start\S*"]
for pname in ["bootargs","fastboot","baseparam","kernel"]:
    off,ln = PARTS[pname]
    seg = data[off:off+ln]
    hits=set()
    for pat in patterns:
        for m in re.findall(pat, seg, re.IGNORECASE):
            hits.add(m)
    print(f"\n-- {pname} --")
    if hits:
        for h in sorted(hits):
            try: print("   ", h.decode('latin1'))
            except: print("   ", h)
    else:
        print("    (چیزی یافت نشد)")

# 2) نمایش رشته‌های حاوی 'mem' یا 'cmdline' در bootargs کامل
print("\n=== رشته‌های bootargs که شامل 'mem' یا 'console' یا 'root=' هستند ===")
off,ln = PARTS["bootargs"]
for s in strings(data[off:off+ln], 6):
    sl = s.lower()
    if b"mem" in sl or b"console" in sl or b"root=" in sl or b"bootargs" in sl or b"mmz" in sl:
        print("   ", s.decode('latin1')[:200])

# 3) mmz/CMA اغلب کل رم را نشان می‌دهد؛ در kernel هم بگردیم
print("\n=== رشته‌های حاوی 'mmz' یا 'cma' یا 'mem=' در kernel (نمونهٔ اول چند مورد) ===")
off,ln = PARTS["kernel"]
cnt=0
for s in strings(data[off:off+ln], 6):
    sl=s.lower()
    if b"mem=" in sl or b"mmz" in sl or b"cma" in sl:
        print("   ", s.decode('latin1')[:160]); cnt+=1
        if cnt>=15: break

# 4) کل بلوک softwareinfo برای یادآوری
print("\n=== بلوک softwareinfo (توصیفی، نه لزوماً رم واقعی) ===")
i = data.find(b"MV300")
if i!=-1:
    seg = data[i-40:i+40]
    print("   ", ''.join(chr(x) if 32<=x<=126 else '.' for x in seg))
