#!/usr/bin/env python3
# Download a portable Zig toolchain for Windows x86_64 (no admin, no install).
# Zig's `zig cc` is a drop-in Clang-based cross compiler that can target
# arm-linux-musleabihf and emit a fully static binary for the receiver.
import json, os, sys, urllib.request, zipfile, ssl

DEST = os.path.join(os.path.dirname(__file__), "..", "build", "zig")
DEST = os.path.abspath(DEST)
INDEX = "https://ziglang.org/download/index.json"

ctx = ssl.create_default_context()

def fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)

print("fetching Zig release index ...")
data = json.load(fetch(INDEX))

# pick the newest stable (top non-master key)
ver = None
for k in data.keys():
    if k == "master":
        continue
    ver = k
    break
if not ver:
    ver = "master"
print("selected Zig version:", ver)

rel = data[ver]
key = "x86_64-windows"
if key not in rel:
    print("available:", list(rel.keys()))
    sys.exit("no x86_64-windows build in index")

url = rel[key]["tarball"]
print("downloading:", url)
os.makedirs(DEST, exist_ok=True)
zpath = os.path.join(DEST, "zig.zip")
with fetch(url) as r, open(zpath, "wb") as f:
    total = 0
    while True:
        chunk = r.read(1 << 20)
        if not chunk:
            break
        f.write(chunk)
        total += len(chunk)
        print(f"\r  {total/1e6:.1f} MB", end="", flush=True)
print("\nextracting ...")
with zipfile.ZipFile(zpath) as z:
    z.extractall(DEST)

# find zig.exe
zig_exe = None
for root, _, files in os.walk(DEST):
    if "zig.exe" in files:
        zig_exe = os.path.join(root, "zig.exe")
        break
if not zig_exe:
    sys.exit("zig.exe not found after extract")
print("ZIG_EXE=" + zig_exe)
with open(os.path.join(DEST, "zig_path.txt"), "w") as f:
    f.write(zig_exe)
print("done")
