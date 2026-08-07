#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inspect / restore boot-time load of g_service (no live rmmod).

The firmware loads HiSilicon modules via:
  /etc/init.d/clap-loadmodules -> /lib/modules/4.4.176/extra/load

This tool only comments/uncomments the line:
  insmod g_service.ko

It NEVER runs rmmod (unsafe on this hardware). Changes take effect on the next
reboot. Live TV modules (u_service / usb_f_service / hi_dvb) are left untouched.

WARNING (lab firmware 2026-08-08): ``disable`` + reboot hung on the boot logo and
eventually auto-powered off. Prefer ``status`` / ``enable`` for recovery only.
Do not use ``disable`` on this image unless you have a known-good flash recovery path.

Usage:
  python tools/g_service_bootctl.py status
  python tools/g_service_bootctl.py enable    # restore boot load (then reboot)
  python tools/g_service_bootctl.py disable   # DANGEROUS on current lab image
"""
from __future__ import annotations

import argparse
import socket
import sys
import time

HOST = "192.168.100.102"
PORT = 23
USER = "root"
PASS = "root"

LOAD = "/lib/modules/4.4.176/extra/load"
BACKUP = "/data/load.g_service_bootctl.bak"
MARKER = "spidervip-g_service-bootctl"


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
    strip_iac(s, recv_until(s, [b"login:", b"ogin:"], 8))
    s.sendall(USER.encode() + b"\r\n")
    strip_iac(s, recv_until(s, [b"assword:"], 6))
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
    d = strip_iac(s, recv_until(s, [token.encode()], timeout))
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


def cmd_status(s) -> int:
    print("--- boot script ---")
    print(run(s, "grep -n 'g_service' %s" % LOAD, 15))
    print("--- runtime ---")
    print(run(s, "lsmod | grep -E 'g_service|u_service|usb_f_service|libcomposite|hi_dvb' ; echo ---; cat /proc/loadavg", 15))
    print("--- backup ---")
    print(run(s, "ls -l %s 2>&1" % BACKUP, 10))
    active = run(s, "grep -E '^insmod g_service\\.ko' %s >/dev/null && echo BOOT_LOAD_ON || echo BOOT_LOAD_OFF" % LOAD, 10)
    loaded = run(s, "grep -q '^g_service ' /proc/modules && echo LOADED || echo NOT_LOADED", 10)
    print("RESULT: %s | runtime=%s" % (active.strip().splitlines()[-1], loaded.strip().splitlines()[-1]))
    return 0


def ensure_backup(s) -> None:
    exists = run(s, "[ -f %s ] && echo YES || echo NO" % BACKUP, 10)
    if "YES" in exists:
        print("backup already present: %s" % BACKUP)
        return
    print("creating backup %s ..." % BACKUP)
    print(run(s, "cp -a %s %s && ls -l %s" % (LOAD, BACKUP, BACKUP), 15))


def cmd_disable(s) -> int:
    ensure_backup(s)
    # Idempotent: if already commented with our marker or any comment on that insmod, skip duplicate
    check = run(s, "grep -E '^insmod g_service\\.ko' %s >/dev/null && echo NEED || echo ALREADY" % LOAD, 10)
    if "ALREADY" in check:
        print("boot load already disabled (no active insmod g_service.ko line)")
        return cmd_status(s)

    # Comment only the active insmod line; keep a clear marker comment
    script = (
        "sed -i 's/^insmod g_service\\.ko$/#insmod g_service.ko  # %s: boot-disabled (do not rmmod live)/' %s && "
        "grep -n 'g_service' %s"
    ) % (MARKER, LOAD, LOAD)
    print(run(s, script, 20))
    print("\nOK: g_service will NOT load on next boot.")
    print("Reboot the receiver to apply (soft reboot is enough for this change).")
    print("Rollback: python tools/g_service_bootctl.py enable")
    return 0


def cmd_enable(s) -> int:
    ensure_backup(s)
    check = run(s, "grep -E '^insmod g_service\\.ko' %s >/dev/null && echo ON || echo OFF" % LOAD, 10)
    if "ON" in check:
        print("boot load already enabled")
        return cmd_status(s)

    # Prefer restoring from backup if our edit is present; else uncomment
    print(run(
        s,
        "if grep -q '%s' %s 2>/dev/null; then "
        "sed -i 's/^#insmod g_service\\.ko.*/insmod g_service.ko/' %s; "
        "else cp -a %s %s; fi; grep -n 'g_service' %s"
        % (MARKER, LOAD, LOAD, BACKUP, LOAD, LOAD),
        20,
    ))
    print("\nOK: g_service will load on next boot. Reboot to apply.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Boot-time g_service load control (no live rmmod)")
    ap.add_argument("action", choices=["status", "disable", "enable"])
    ap.add_argument("--host", default=HOST)
    args = ap.parse_args()

    print("connecting to %s ..." % args.host, flush=True)
    s = login(args.host)
    print("LOGIN OK", flush=True)
    try:
        if args.action == "status":
            return cmd_status(s)
        if args.action == "disable":
            return cmd_disable(s)
        return cmd_enable(s)
    finally:
        try:
            s.sendall(b"exit\r\n")
        except Exception:
            pass
        s.close()


if __name__ == "__main__":
    sys.exit(main())
