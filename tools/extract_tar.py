#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spider VIP - استخراج درخت فایل rootfs (tar)
==========================================
rootfs.unpacked یک آرشیو tar است. این اسکریپت آن را استخراج کرده
و خلاصه‌ای از ساختار درخت + فایل‌های اجرایی (باینری برنامه STB) می‌دهد.
"""

import sys
import os
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRACTED = os.path.join(os.path.dirname(HERE), "extracted")
ROOTFS_DIR = os.path.join(EXTRACTED, "rootfs_tree")


def human(n):
    x = float(n)
    for u in ["B", "KB", "MB", "GB"]:
        if x < 1024:
            return f"{int(n)}{u}" if u == "B" else f"{x:.1f}{u}"
        x /= 1024
    return f"{x:.1f}TB"


def main():
    src = os.path.join(EXTRACTED, "rootfs.unpacked")
    if not os.path.isfile(src):
        print(f"[!] یافت نشد: {src}")
        sys.exit(1)

    os.makedirs(ROOTFS_DIR, exist_ok=True)

    print("=" * 70)
    print("  استخراج درخت فایل rootfs (tar)")
    print("=" * 70)

    members = []
    count = 0
    big_files = []
    with tarfile.open(src, "r:*") as tar:
        for m in tar:
            members.append((m.name, m.size, m.isdir(), m.mode))
            if m.isfile() and m.size > 500 * 1024:
                big_files.append((m.name, m.size))
            try:
                # استخراج امن
                tar.extract(m, ROOTFS_DIR, filter="tar")
            except Exception:
                try:
                    tar.extract(m, ROOTFS_DIR)
                except Exception as ex:
                    pass
            count += 1
            if count % 500 == 0:
                sys.stdout.write(f"\r    استخراج: {count} فایل")
                sys.stdout.flush()
    print(f"\r    استخراج کامل: {count} عضو")

    dirs = [m for m in members if m[2]]
    files = [m for m in members if not m[2]]
    print(f"  تعداد پوشه: {len(dirs)}  |  تعداد فایل: {len(files)}")

    # پوشه‌های سطح بالا
    top = sorted(set(m[0].split("/")[1] for m in members if m[0].startswith("./") and len(m[0].split("/")) > 1 and m[0].split("/")[1]))
    print("\n  [ پوشه‌های سطح بالای rootfs ]")
    for d in top:
        print(f"    /{d}")

    # بزرگترین فایل‌ها (کاندید باینری برنامه اصلی)
    print("\n  [ بزرگترین فایل‌ها (کاندید باینری برنامه STB) ]")
    for name, size in sorted(big_files, key=lambda x: -x[1])[:30]:
        print(f"    {human(size):>10}  {name}")

    # ذخیره فهرست کامل
    report = os.path.join(os.path.dirname(HERE), "docs", "rootfs_filelist.txt")
    with open(report, "w", encoding="utf-8") as r:
        for name, size, isdir, mode in members:
            kind = "DIR " if isdir else "FILE"
            r.write(f"{kind} {size:>12} {oct(mode)} {name}\n")
    print(f"\n  فهرست کامل فایل‌ها: {report}")
    print("=" * 70)


if __name__ == "__main__":
    main()
