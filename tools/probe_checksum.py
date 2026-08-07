#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""کشف الگوریتم فیلد چهارم (احتمالی checksum) برای rootfs و user"""
import struct, zlib

F = r"F:\Satelite\Spider VIP\SPIDER-VIP_v1.00.92_20260507.mupg"

# (name, img_len, file_off, flags_low24)
targets = [
    ("rootfs", 0x1D5699FC, 0x0123EF96, 0x0FD868),
    ("user",   0x0120E522, 0x1E7A8992, 0x008430),
]

def sum8(d):   return sum(d) & 0xFFFFFF
def sum16(d):
    s=0
    for i in range(0,len(d)-1,2): s+=d[i]|(d[i+1]<<8)
    if len(d)&1: s+=d[-1]
    return s & 0xFFFFFF
def sum32le(d):
    s=0
    n=len(d)-(len(d)%4)
    for i in range(0,n,4): s+=struct.unpack_from("<I",d,i)[0]
    return s & 0xFFFFFF
def xor32(d):
    x=0
    n=len(d)-(len(d)%4)
    for i in range(0,n,4): x^=struct.unpack_from("<I",d,i)[0]
    return x & 0xFFFFFF

with open(F,"rb") as f:
    for name, il, off, target in targets:
        f.seek(off); data=f.read(il)
        cands = {
            "len&0xFFFFFF"      : il & 0xFFFFFF,
            "crc32&0xFFFFFF"    : zlib.crc32(data)&0xFFFFFF,
            "crc32>>8"          : (zlib.crc32(data)>>8)&0xFFFFFF,
            "sum8&0xFFFFFF"     : sum8(data),
            "sum16&0xFFFFFF"    : sum16(data),
            "sum32le&0xFFFFFF"  : sum32le(data),
            "xor32&0xFFFFFF"    : xor32(data),
            "adler32&0xFFFFFF"  : zlib.adler32(data)&0xFFFFFF,
        }
        print(f"\n=== {name}  target=0x{target:06X}  img_len=0x{il:X} ===")
        for k,v in cands.items():
            hit = "  <-- MATCH!" if v==target else ""
            print(f"   {k:<18} = 0x{v:06X}{hit}")
