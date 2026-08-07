#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pull freeze forensic snapshots from the receiver to build/freeze_snap/.

After a hard power-cycle recovery, snapshots under /data/freeze_snap/ remain.
This tool tars the newest (or all) snapshot dirs and pulls them via Telnet.

Usage:
  python tools/freeze_pull.py              # latest snapshot only
  python tools/freeze_pull.py --all        # every snapshot
  python tools/freeze_pull.py --list       # list remote snaps only
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import socket
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "build", "freeze_snap")
DEFAULT_HOST = "192.168.100.102"
PORT = 23
USER = "root"
PASS = "root"
REMOTE_BASE = "/data/freeze_snap"


def recv_until(sock, markers, timeout=60):
    sock.settimeout(0.8)
    buf = b""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            data = sock.recv(16384)
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
    recv_until(s, [b"# ", b"#\r", b"~#"], 8)
    s.sendall(b"export PS1='PROMPT> '\r\n")
    recv_until(s, [b"PROMPT> "], 5)
    return s


_run_idx = 0


def run(s, cmd, timeout=60):
    global _run_idx
    _run_idx += 1
    idx = _run_idx
    token = "MK%dEND" % idx
    s.sendall(cmd.encode() + b"\r\n")
    s.sendall(('echo "MK""%d""END"' % idx).encode() + b"\r\n")
    d = recv_until(s, [token.encode()], timeout)
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


def pull_b64_file(s, remote_path: str, timeout=120) -> bytes:
    """Cat a remote file as base64 between sentinels that are not echoed whole."""
    # Build sentinels at runtime so the command echo cannot contain the full marker.
    cmd = (
        "S=FZ; echo ${S}STA RT | tr -d ' '; "
        "base64 '%s' 2>/dev/null || base64 < '%s'; "
        "echo; echo ${S}EN D | tr -d ' '"
    ) % (remote_path, remote_path)
    s.sendall(cmd.encode() + b"\r\n")
    d = recv_until(s, [b"FZEND"], timeout)
    d = strip_iac(s, d).decode(errors="replace")
    matches = list(re.finditer(r"FZSTART(.*?)FZEND", d, re.S))
    if not matches:
        return b""
    blob = "".join(re.findall(r"[A-Za-z0-9+/=]", matches[-1].group(1)))
    if not blob:
        return b""
    return base64.b64decode(blob + "=" * (-len(blob) % 4))


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def list_snaps(s) -> list[str]:
    # busybox ls may colorize; strip ANSI and take basename-like tokens
    out = run(s, "ls -1 --color=never %s 2>/dev/null || ls -1 %s 2>/dev/null" % (REMOTE_BASE, REMOTE_BASE), 20)
    names = []
    for ln in out.splitlines():
        ln = _ANSI_RE.sub("", ln).strip()
        if not ln or ln.startswith("PROMPT") or " " in ln:
            continue
        # drop path prefix if present
        ln = ln.rstrip("/").split("/")[-1]
        if re.match(r"^[\w.-]+$", ln):
            names.append(ln)
    return sorted(set(names))


def main() -> int:
    ap = argparse.ArgumentParser(description="Pull /data/freeze_snap to build/freeze_snap")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--all", action="store_true", help="pull every snapshot")
    ap.add_argument("--list", action="store_true", help="list remote snapshots only")
    ap.add_argument("--name", help="pull a specific snapshot directory name")
    args = ap.parse_args()

    print("connecting to %s ..." % args.host, flush=True)
    s = login(args.host)
    print("LOGIN OK", flush=True)

    snaps = list_snaps(s)
    if not snaps:
        print("No snapshots under %s" % REMOTE_BASE)
        try:
            s.sendall(b"exit\r\n")
        except Exception:
            pass
        s.close()
        return 1

    print("Remote snapshots:")
    for n in snaps:
        print("  %s" % n)

    if args.list:
        try:
            s.sendall(b"exit\r\n")
        except Exception:
            pass
        s.close()
        return 0

    if args.name:
        selected = [args.name]
        if args.name not in snaps:
            print("WARNING: %s not in ls; trying anyway" % args.name)
    elif args.all:
        selected = snaps
    else:
        selected = [snaps[-1]]
        print("Pulling latest: %s" % selected[0])

    os.makedirs(OUT_DIR, exist_ok=True)

    for name in selected:
        remote_dir = "%s/%s" % (REMOTE_BASE, name)
        remote_tar = "/tmp/freeze_%s.tar" % name.replace("/", "_")
        print("packing %s ..." % name, flush=True)
        # busybox tar: create from parent so archive contains the snap folder
        pack = run(
            s,
            "rm -f %s; tar -C %s -cf %s %s 2>&1; ls -l %s" % (
                remote_tar, REMOTE_BASE, remote_tar, name, remote_tar
            ),
            60,
        )
        print(pack, flush=True)
        print("pulling base64 ...", flush=True)
        raw = pull_b64_file(s, remote_tar, timeout=180)
        run(s, "rm -f %s" % remote_tar, 15)
        if not raw:
            print("FAILED to pull %s" % name, file=sys.stderr)
            continue
        local_tar = os.path.join(OUT_DIR, "%s.tar" % name)
        with open(local_tar, "wb") as f:
            f.write(raw)
        # extract
        dest = os.path.join(OUT_DIR, name)
        os.makedirs(dest, exist_ok=True)
        try:
            with tarfile.open(local_tar, "r:") as tf:
                tf.extractall(OUT_DIR)
            print("SAVED %s (%d bytes tar) -> %s" % (local_tar, len(raw), dest), flush=True)
            summary = os.path.join(OUT_DIR, name, "SUMMARY.txt")
            if os.path.isfile(summary):
                print("--- SUMMARY ---")
                print(open(summary, encoding="utf-8", errors="replace").read())
        except Exception as exc:
            print("tar extract failed (%s); kept %s" % (exc, local_tar), file=sys.stderr)

    try:
        s.sendall(b"exit\r\n")
    except Exception:
        pass
    s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
