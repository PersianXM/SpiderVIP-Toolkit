#!/usr/bin/env python3
# Cross-compile dbgbar for the receiver (ARMv7 / Cortex-A7, musl static)
# using the portable Zig toolchain. Avoids PowerShell arg-quoting issues.
import os, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRCDIR = os.path.join(ROOT, "patches", "usr", "local", "dbgbar")
ZIG = os.path.join(ROOT, "build", "zig", "zig-x86_64-windows-0.16.0", "zig.exe")
OUT = os.path.join(SRCDIR, "dbgbar")

srcs = ["main.c", "config.c", "providers.c", "render.c"]

cmd = [
    ZIG, "cc",
    "-target", "arm-linux-musleabihf",
    "-mcpu=cortex_a7",
    "-Os", "-static",
    "-ffunction-sections", "-fdata-sections",
    "-Wl,--gc-sections",
    "-std=gnu99",
    "-o", OUT,
] + srcs

print("CWD:", SRCDIR)
print("CMD:", " ".join(cmd))
r = subprocess.run(cmd, cwd=SRCDIR)
if r.returncode != 0:
    sys.exit("compile FAILED rc=%d" % r.returncode)

sz = os.path.getsize(OUT)
print("OK: built %s  (%d bytes)" % (OUT, sz))

# quick sanity: ELF header + machine = ARM (0x28)
with open(OUT, "rb") as f:
    hdr = f.read(20)
if hdr[:4] != b"\x7fELF":
    sys.exit("output is not an ELF file")
machine = hdr[18] | (hdr[19] << 8)
print("ELF class=%d(%s) endian=%d machine=0x%02x(%s)" % (
    hdr[4], "32-bit" if hdr[4]==1 else "64-bit",
    hdr[5], machine, "ARM" if machine==0x28 else "?"))
if machine != 0x28:
    sys.exit("WRONG ARCH: expected ARM (0x28)")
print("ARCH OK: ARM 32-bit static ELF ready for the receiver")
