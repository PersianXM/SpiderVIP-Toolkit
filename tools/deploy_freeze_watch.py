#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deploy on-box freeze watcher to /data/freeze_tools and start it.

Installs:
  /data/freeze_tools/freeze_dump.sh
  /data/freeze_tools/freeze_watch.sh
  /data/freeze_tools/freeze_watch.conf
  /data/freeze_tools/autostart.sh
  /home/gx/local/user_script  (hook used by bianbiang.sh start_services)

Does not modify /usr/bin/bianbiang.sh on the live box.

Usage:
  python tools/deploy_freeze_watch.py
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
FILES = {
    "freeze_dump.sh": os.path.join(HERE, "freeze_dump.sh"),
    "freeze_watch.sh": os.path.join(HERE, "freeze_watch.sh"),
}

REMOTE_DIR = "/data/freeze_tools"
DEFAULT_HOST = "192.168.100.102"
PORT = 23
USER = "root"
PASS = "root"

CONF_BODY = """# freeze_watch.conf
INTERVAL_SEC=30
HOLD_SEC=60
COOLDOWN_SEC=1800
"""

AUTOSTART_BODY = """#!/bin/sh
# Start freeze watch once per boot (idempotent).
TOOLS=/data/freeze_tools
if [ -f "$TOOLS/freeze_watch.sh" ]; then
    if ! pidof -x freeze_watch.sh >/dev/null 2>&1; then
        # busybox pidof may not support -x; fall back to grep
        if ! ps ax 2>/dev/null | grep -v grep | grep -q '[f]reeze_watch.sh'; then
            sh "$TOOLS/freeze_watch.sh" >/dev/null 2>&1 &
        fi
    fi
fi
"""

USER_SCRIPT_BODY = """#!/bin/sh
# SpiderVIP freeze forensic autostart (managed by deploy_freeze_watch.py)
if [ -x /data/freeze_tools/autostart.sh ] || [ -f /data/freeze_tools/autostart.sh ]; then
    sh /data/freeze_tools/autostart.sh &
fi
"""


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


def push_bytes(s, raw: bytes, remote_path: str) -> str:
    raw = raw.replace(b"\r\n", b"\n")
    md5 = hashlib.md5(raw).hexdigest()
    b64 = base64.b64encode(raw).decode("ascii")
    remote_b64 = "/tmp/freeze_push.b64"
    run(s, "rm -f %s %s" % (remote_b64, remote_path), 15)
    chunk = 1800
    n = (len(b64) + chunk - 1) // chunk
    for i in range(0, len(b64), chunk):
        part = b64[i : i + chunk]
        run(s, "printf '%%s' '%s' >> %s" % (part, remote_b64), 20)
        print("\r  %s: chunk %d/%d" % (os.path.basename(remote_path), i // chunk + 1, n), end="", flush=True)
    print()
    run(s, "base64 -d %s > %s" % (remote_b64, remote_path), 30)
    run(s, "chmod 755 %s" % remote_path, 10)
    return md5


def push_file(s, local_path: str, remote_path: str) -> str:
    with open(local_path, "rb") as f:
        return push_bytes(s, f.read(), remote_path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Deploy freeze_watch to the receiver")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--no-start", action="store_true", help="install only; do not start watcher")
    args = ap.parse_args()

    for name, path in FILES.items():
        if not os.path.isfile(path):
            print("missing %s" % path, file=sys.stderr)
            return 1

    print("connecting to %s ..." % args.host, flush=True)
    s = login(args.host)
    print("LOGIN OK", flush=True)

    run(s, "mkdir -p %s /data/freeze_snap /home/gx/local" % REMOTE_DIR, 15)

    for name, path in FILES.items():
        print("pushing %s ..." % name, flush=True)
        md5 = push_file(s, path, "%s/%s" % (REMOTE_DIR, name))
        remote = run(s, "md5sum %s/%s" % (REMOTE_DIR, name), 15).split()
        remote = remote[0] if remote else "?"
        print("  md5 %s %s" % (md5, "OK" if md5 == remote else "MISMATCH(%s)" % remote))

    print("pushing conf + autostart + user_script ...", flush=True)
    push_bytes(s, CONF_BODY.encode(), REMOTE_DIR + "/freeze_watch.conf")
    push_bytes(s, AUTOSTART_BODY.encode(), REMOTE_DIR + "/autostart.sh")
    # Only replace user_script if missing or previously ours
    existing = run(s, "head -n 1 /home/gx/local/user_script 2>/dev/null", 10)
    if (not existing.strip()) or "freeze forensic" in existing or "freeze_tools" in existing:
        push_bytes(s, USER_SCRIPT_BODY.encode(), "/home/gx/local/user_script")
        print("  user_script installed")
    else:
        # append hook once
        marker = run(s, "grep -c freeze_tools /home/gx/local/user_script 2>/dev/null || echo 0", 10)
        if marker.strip().splitlines()[-1:] == ["0"] or marker.strip() == "0":
            run(
                s,
                "printf '\\n# freeze forensic\\nsh /data/freeze_tools/autostart.sh &\\n' >> /home/gx/local/user_script",
                15,
            )
            print("  user_script: appended autostart hook")
        else:
            print("  user_script: freeze hook already present")

    if not args.no_start:
        print("starting watcher ...", flush=True)
        # Replace any old watcher with the newly pushed script
        run(s, "killall freeze_watch.sh 2>/dev/null; kill $(ps ax | grep '[f]reeze_watch.sh' | awk '{print $1}') 2>/dev/null; true", 15)
        time.sleep(1)
        run(s, "sh %s/freeze_watch.sh >/dev/null 2>&1 &" % REMOTE_DIR, 15)
        time.sleep(1)
        ps = run(s, "ps ax 2>/dev/null | grep '[f]reeze_watch.sh' || echo NONE", 15)
        print("watcher: %s" % (ps if ps.strip() else "NONE"), flush=True)

    print("DONE. Manual capture: python tools/freeze_capture.py", flush=True)
    try:
        s.sendall(b"exit\r\n")
    except Exception:
        pass
    s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
