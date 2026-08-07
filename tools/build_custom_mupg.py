#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_custom_mupg.py
====================
ساخت نسخهٔ سفارشی فایل فریمویر Spider VIP با اعمال patchهای پایداری.

روش کار (ایمن، بدون خرابی متادیتا):
  1) rootfs اصلی (tar.gz) از داخل .mupg خوانده می‌شود.
  2) tar عضو‌به‌عضو بازنویسی می‌شود؛ همهٔ متادیتا (mode/uid/gid/symlink/
     device/hardlink) عیناً حفظ و فقط فایل‌های داخل patches/ جایگزین می‌شوند.
  3) دوباره gzip می‌شود.
  4) اگر gzip جدید <= img_len اصلی بود  ->  با صفر تا اندازهٔ اصلی pad می‌شود
     => هیچ فیلدی در هدر .mupg تغییر نمی‌کند  =>  امن‌ترین حالت (SAFE MODE).
     در غیر این صورت  ->  img_len و فیلد اندازهٔ 0x50 به‌روز می‌شوند (RESIZE MODE،
     همراه هشدار دربارهٔ فیلد flags که رمزگشایی نشده).

خروجی در: build/
"""
import os, sys, io, gzip, struct, tarfile, hashlib

SRC_MUPG   = r"F:\Satelite\Spider VIP\SPIDER-VIP_v1.00.92_20260507.mupg"
PROJ       = r"G:\Spider-VIP-Firmware-Project"
PATCH_DIR  = os.path.join(PROJ, "patches")
BUILD_DIR  = os.path.join(PROJ, "build")
OUT_MUPG   = os.path.join(BUILD_DIR, "SPIDER-VIP_v1.00.92_CUSTOM.mupg")
OUT_ROOTFS = os.path.join(BUILD_DIR, "rootfs_custom.tar.gz")

ROOTFS_OFF = 0x0123EF96          # file offset پارتیشن rootfs
DATA_START = 0x1000
SIZE_FIELD = 0x50                # فیلد اندازه (= filesize - 0x400)

# نگاشت: نام عضو داخل tar  ->  فایل patch روی دیسک
PATCH_MAP = {
    "./usr/bin/bianbiang.sh": os.path.join(PATCH_DIR, "usr", "bin", "bianbiang.sh"),
    "./etc/sysctl.conf":      os.path.join(PATCH_DIR, "etc", "sysctl.conf"),
}

# جایگزینی باینری هم‌طول داخل اعضای rootfs (در صورت نیاز). فعلاً خالی —
# چون منبع واقعیِ نمایشِ SW version در بلوک‌های softwareinfo خارج از rootfs است
# (هدر mupg + انتهای پارتیشن logo)، نه در باینری bianbiang.
BINARY_PATCH_MAP = {}

# ------------------------------------------------------------------
# patch مستقیم بایت‌های خام mupg، خارج از rootfs (SW version واقعی).
# ساختار بلوک softwareinfo:  "IP".. 1.00.00 .. <SWVER> .. 3798 MV300 DDR 1GB TOP 8GB
# سه نسخه از این بلوک وجود دارد؛ همه باید یکسان patch شوند تا هماهنگ بمانند:
#   0x28  (HEADER #1)  |  0x434 (HEADER #2)  |  0x1BE31C (انتهای پارتیشن logo، runtime)
# جایگزینی هم‌طول است؛ پارتیشن‌های header/logo فاقد checksum هستند (flags low24=0).
RAW_PATCH_MAP = [
    # (توضیح, old_bytes, new_bytes)  — old باید یکتا-به-تعداد و هم‌طول new باشد
    ("SW version", b"1.00.92\x00", b"1.00.93\x00"),
]



def log(m): print(m, flush=True)

def read_head():
    with open(SRC_MUPG, "rb") as f:
        return bytearray(f.read(DATA_START))

def find_rootfs_entry(head):
    idx = head.find(b"rootfs\x00", 0x800)
    part, img, flash, flags = struct.unpack(">IIII", head[idx+20:idx+36])
    return idx, part, img, flash, flags

def rewrite_tar():
    """tar.gz را با اعمال patchها بازنویسی و به‌صورت gzip در حافظه برمی‌گرداند."""
    # بارگذاری محتوای patchها
    patch_bytes = {}
    for name, path in PATCH_MAP.items():
        with open(path, "rb") as pf:
            patch_bytes[name] = pf.read()
        log(f"  patch loaded: {name}  ({len(patch_bytes[name])} bytes)")

    src = open(SRC_MUPG, "rb")
    src.seek(ROOTFS_OFF)
    tin = tarfile.open(fileobj=src, mode="r|gz")

    gz_buf = io.BytesIO()
    gz = gzip.GzipFile(fileobj=gz_buf, mode="wb", compresslevel=9, mtime=0)
    tout = tarfile.open(fileobj=gz, mode="w|", format=tarfile.GNU_FORMAT)

    count = patched = binpatched = 0
    for m in tin:
        count += 1
        if m.name in patch_bytes and m.isreg():
            # جایگزینی کامل فایل (اسکریپت/کانفیگ)
            data = patch_bytes[m.name]
            ti = tarfile.TarInfo(m.name)
            # حفظ کامل متادیتای اصلی، فقط اندازه تغییر می‌کند
            ti.mode = m.mode; ti.uid = m.uid; ti.gid = m.gid
            ti.uname = m.uname; ti.gname = m.gname
            ti.mtime = m.mtime; ti.type = tarfile.REGTYPE
            ti.size = len(data)
            tout.addfile(ti, io.BytesIO(data))
            patched += 1
            log(f"  >> patched member: {m.name} ({m.size} -> {len(data)})")
        elif m.name in BINARY_PATCH_MAP and m.isreg():
            # جایگزینی باینری هم‌طول (اندازه و متادیتا بدون تغییر)
            raw = bytearray(tin.extractfile(m).read())
            for old, new in BINARY_PATCH_MAP[m.name]:
                if len(old) != len(new):
                    raise ValueError(f"binary patch not equal length for {m.name}")
                cnt = raw.count(old)
                if cnt == 0:
                    log(f"  !! هشدار: الگو در {m.name} یافت نشد: {old!r}")
                elif cnt > 1:
                    raise ValueError(f"binary pattern {old!r} appears {cnt}x in {m.name} (باید یکتا باشد)")
                else:
                    raw[:] = raw.replace(old, new)
                    binpatched += 1
                    log(f"  >> binary-patched {m.name}: {old!r} -> {new!r}")
            # size باید دقیقاً همان اندازهٔ اصلی بماند
            assert len(raw) == m.size, (len(raw), m.size)
            tout.addfile(m, io.BytesIO(bytes(raw)))
        else:
            if m.isreg():
                fobj = tin.extractfile(m)
                tout.addfile(m, fobj)
            else:
                # symlink / dir / device / fifo / hardlink -> بدون داده، متادیتا کامل
                tout.addfile(m)
    tout.close(); gz.close()
    tin.close(); src.close()

    log(f"  tar members: {count}  |  file-patched: {patched}  |  binary-patched: {binpatched}")
    if patched != len(PATCH_MAP):
        log("  !! هشدار: همهٔ فایل‌های patch در tar یافت/جایگزین نشدند")
    return gz_buf.getvalue()


def main():
    os.makedirs(BUILD_DIR, exist_ok=True)
    filesize = os.path.getsize(SRC_MUPG)
    head = read_head()
    ridx, rpart, rimg, rflash, rflags = find_rootfs_entry(head)
    log(f"rootfs entry @0x{ridx:X}  img_len=0x{rimg:X}  flash=0x{rflash:X}  flags=0x{rflags:08X}")
    log(f"filesize=0x{filesize:X}  size_field(orig)=0x{struct.unpack('>I',head[SIZE_FIELD:SIZE_FIELD+4])[0]:X}")

    log("\n[1/3] بازنویسی و فشرده‌سازی rootfs ...")
    new_gz = rewrite_tar()
    with open(OUT_ROOTFS, "wb") as f:
        f.write(new_gz)
    log(f"  new rootfs.gz size = 0x{len(new_gz):X} ({len(new_gz)} bytes)")
    log(f"  original img_len   = 0x{rimg:X} ({rimg} bytes)")

    # اعتبارسنجی: gzip جدید باید سالم باز شود
    log("\n[2/3] اعتبارسنجی gzip جدید ...")
    try:
        with gzip.open(io.BytesIO(new_gz), "rb") as g:
            n = 0
            while True:
                b = g.read(8*1024*1024)
                if not b: break
                n += len(b)
        log(f"  OK — decompresses to {n} bytes tar")
    except Exception as e:
        log(f"  !! خطا در اعتبارسنجی gzip: {e}")
        sys.exit(1)

    # تعیین حالت
    tail_after_rootfs = filesize - (ROOTFS_OFF + rimg)   # بایت‌های پارتیشن user
    log(f"\n[3/3] ساخت .mupg ...")
    log(f"  user tail bytes = {tail_after_rootfs} (0x{tail_after_rootfs:X})")

    with open(SRC_MUPG, "rb") as f:
        pre  = f.read(ROOTFS_OFF)          # هدر + پارتیشن‌های 0..7 (بدون تغییر)
        f.seek(ROOTFS_OFF + rimg)
        tail = f.read()                    # پارتیشن user (بدون تغییر)

    new_head = bytearray(pre[:DATA_START]) # کپی هدر برای احتمال ویرایش
    body_pre = pre[DATA_START:]            # پارتیشن‌های 0..7

    if len(new_gz) <= rimg:
        # ---------- SAFE MODE: pad تا اندازهٔ اصلی، هیچ تغییری در هدر ----------
        pad = rimg - len(new_gz)
        rootfs_final = new_gz + (b"\x00" * pad)
        mode = "SAFE (padded, header unchanged)"
        log(f"  SAFE MODE: pad {pad} bytes صفر تا img_len اصلی — هدر دست‌نخورده")
        out = bytes(new_head) + body_pre + rootfs_final + tail
        assert len(out) == filesize, (len(out), filesize)
    else:
        # ---------- RESIZE MODE: به‌روزرسانی img_len و فیلد اندازه ----------
        mode = "RESIZE (img_len & size field updated) — فیلد flags رمزگشایی نشده!"
        new_img = len(new_gz)
        # به‌روزرسانی img_len rootfs (بایت‌های 24..28 رکورد)
        struct.pack_into(">I", new_head, ridx+24, new_img)
        out = bytes(new_head) + body_pre + new_gz + tail
        new_filesize = len(out)
        # فیلد اندازه = filesize - 0x400
        struct.pack_into(">I", out_ba := bytearray(out), SIZE_FIELD, new_filesize - 0x400)
        out = bytes(out_ba)
        log(f"  RESIZE MODE: img_len 0x{rimg:X} -> 0x{new_img:X}; size_field=0x{new_filesize-0x400:X}")
        log("  !! هشدار: فیلد flags (0x010FD868) رمزگشایی نشد و به‌روز نشده است.")

    # ---------- اعمال raw-patchها روی بایت‌های خام mupg (خارج از rootfs) ----------
    if RAW_PATCH_MAP:
        log("\n[raw] اعمال patch مستقیم بایتی (softwareinfo/SW version) ...")
        out_ba = bytearray(out)
        for desc, old, new in RAW_PATCH_MAP:
            if len(old) != len(new):
                raise ValueError(f"raw patch not equal length: {desc}")
            cnt = out_ba.count(old)
            if cnt == 0:
                log(f"  !! هشدار: '{desc}' الگو یافت نشد: {old!r}")
            else:
                out_ba[:] = out_ba.replace(old, new)
                # پیدا کردن آفست‌ها برای گزارش
                offs, s = [], 0
                tmp = bytes(out)
                while True:
                    j = tmp.find(old, s)
                    if j == -1: break
                    offs.append(j); s = j + 1
                log(f"  >> {desc}: {old!r} -> {new!r}  ({cnt} مورد @ " +
                    ", ".join(f"0x{o:X}" for o in offs) + ")")
        out = bytes(out_ba)
        assert len(out) == filesize if mode.startswith("SAFE") else True

    with open(OUT_MUPG, "wb") as f:
        f.write(out)


    log("\n==================== نتیجه ====================")
    log(f"  حالت ساخت : {mode}")
    log(f"  خروجی     : {OUT_MUPG}")
    log(f"  اندازه    : {len(out)} bytes (0x{len(out):X})")
    log(f"  md5       : {hashlib.md5(out).hexdigest()}")
    log("===============================================")

if __name__ == "__main__":
    main()
