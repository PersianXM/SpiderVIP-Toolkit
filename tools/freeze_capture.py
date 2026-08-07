#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Take an immediate durable freeze forensic snapshot on the receiver.

Pushes tools/freeze_dump.sh to /data/freeze_tools/ if needed, runs it with
reason=manual, prints SUMMARY. Snapshots survive hard power-cut on /data.

Usage:
  python tools/freeze_capture.py
  python tools/freeze_capture.py --host 192.168.100.102
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP_LOCAL = os.path.join(HERE, "freeze_dump.sh")
REMOTE_DIR = "/data/freeze_tools"
REMOTE_DUMP = REMOTE_DIR + "/freeze_dump.sh"

DEFAULT_HOST = "192.168.100.102"
PORT = 23
USER = "root"
PASS = "root"


def recv_until(sock, markers, timeout=30):
    sock.settimeout(0.8)
    buf = b""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            data = sock.recv(8192)
            if not data:
                break
            buf += data
            for m in markers:
                if m in buf:
                    return buf
        except socket.timeout:
            for m in markers:
                if m in buf:
                    return buf
            continue
        except Exception:
            break
    return buf


def strip_iac(sock, data):
    IAC, DO, DONT, WILL, WONT, SB, SE = 255, 253, 254, 251, 252, 250, 240
    out = bytearray()
    clean = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == IAC and i + 2 < len(data):
            cmd, opt = data[i + 1], data[i + 2]
            if cmd == DO:
                out += bytes([IAC, WONT, opt])
            elif cmd == WILL:
                out += bytes([IAC, DONT, opt])
            i += 3
            continue
        if b == IAC and i + 1 < len(data) and data[i + 1] == SB:
            j = i + 2
            while j < len(data) and data[j] != SE:
                j += 1
            i = j + 1
            continue
        clean.append(b)
        i += 1
    if out:
        try:
            sock.sendall(bytes(out))
        except Exception:
            pass
    return bytes(clean)


def login(host: str):
    s = socket.create_connection((host, PORT), timeout=10)
    d = recv_until(s, [b"login:", b"ogin:"], 8)
    strip_iac(s, d)
    s.sendall(USER.encode() + b"\r\n")
    d = recv_until(s, [b"assword:"], 6)
    strip_iac(s, d)
    s.sendall(PASS.encode() + b"\r\n")
    d = recv_until(s, [b"# ", b"#\r", b"~#", b"incorrect"], 8)
    if b"incorrect" in d.lower():
        raise RuntimeError("login incorrect")
    s.sendall(b"export PS1='PROMPT> '\r\n")
    recv_until(s, [b"PROMPT> "], 5)
    return s


def run(s, cmd, timeout=120, idx=0):
    # Same sentinel style as telnet_run.py — echo line cannot false-match marker.
    token = "MK%dEND" % idx
    marker = token.encode()
    s.sendall(cmd.encode() + b"\r\n")
    s.sendall(('echo "MK""%d""END"' % idx).encode() + b"\r\n")
    d = recv_until(s, [marker], timeout)
    d = strip_iac(s, d)
    txt = d.decode(errors="replace")
    keep = []
    for ln in txt.splitlines():
        st = ln.strip()
        if cmd.strip() and cmd.strip() in ln:
            continue
        if ('echo "MK""%d""END"' % idx) in ln:
            continue
        if token in ln:
            continue
        if st == "PROMPT>" or st.endswith("PROMPT>"):
            continue
        keep.append(ln)
    return "\n".join(keep).strip("\n")


def push_text(s, local_path: str, remote_path: str) -> str:
    with open(local_path, "rb") as f:
        raw = f.read()
    # normalize to LF for the box
    raw = raw.replace(b"\r\n", b"\n")
    md5 = hashlib.md5(raw).hexdigest()
    b64 = base64.b64encode(raw).decode("ascii")
    remote_b64 = "/tmp/freeze_push.b64"
    run(s, "rm -f %s %s" % (remote_b64, remote_path), 15, idx=10)
    chunk = 1800
    for i in range(0, len(b64), chunk):
        part = b64[i : i + chunk]
        run(s, "printf '%%s' '%s' >> %s" % (part, remote_b64), 20, idx=11 + i // chunk)
    run(s, "base64 -d %s > %s" % (remote_b64, remote_path), 30, idx=90)
    run(s, "chmod 755 %s" % remote_path, 10, idx=91)
    return md5


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture freeze forensics to /data/freeze_snap")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--reason", default="manual", help="tag stored in meta/SUMMARY")
    args = ap.parse_args()

    if not os.path.isfile(DUMP_LOCAL):
        print("missing %s" % DUMP_LOCAL, file=sys.stderr)
        return 1

    print("connecting to %s ..." % args.host, flush=True)
    s = login(args.host)
    print("LOGIN OK", flush=True)

    run(s, "mkdir -p %s /data/freeze_snap" % REMOTE_DIR, 15, idx=1)
    run(s, "rm -f %s/dump.lock" % REMOTE_DIR, 10, idx=2)
    print("pushing freeze_dump.sh ...", flush=True)
    md5 = push_text(s, DUMP_LOCAL, REMOTE_DUMP)
    remote_md5 = run(s, "md5sum %s" % REMOTE_DUMP, 15, idx=3).split()
    remote_md5 = remote_md5[0] if remote_md5 else "?"
    print("md5 host=%s device=%s %s" % (md5, remote_md5, "OK" if md5 == remote_md5 else "MISMATCH"))

    print("running dump (reason=%s) ..." % args.reason, flush=True)
    # IRQ sample sleeps inside dump; allow headroom
    out = run(s, "sh %s %s" % (REMOTE_DUMP, args.reason), 300, idx=4)
    print(out, flush=True)

    # show SUMMARY if path known
    snap = ""
    for ln in out.splitlines():
        if "DUMP_OK" in ln:
            parts = ln.split()
            if len(parts) >= 2:
                snap = parts[1]
    if snap:
        print("\n--- SUMMARY ---", flush=True)
        print(run(s, "cat %s/SUMMARY.txt" % snap, 30, idx=5), flush=True)
        print("\nSnapshot on box: %s" % snap, flush=True)
        print("After recovery: python tools/freeze_pull.py", flush=True)
    else:
        print("WARNING: DUMP_OK not seen; check output above", file=sys.stderr)

    try:
        s.sendall(b"exit\r\n")
    except Exception:
        pass
    s.close()
    return 0 if "DUMP_OK" in out else 2


if __name__ == "__main__":
    sys.exit(main())
