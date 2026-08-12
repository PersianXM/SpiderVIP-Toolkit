#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automated A/V freeze recovery (validated 2026-08-12 on lab Spider VIP).

Playbook:
  1. Optional deploy of patches (bianbiang.sh, sysctl, freeze_watch)
  2. Light A/V health check
  3. backup live_prog -> /data/live_prog_usals_ok.bak
  4. /sbin/reboot -f  (NOT plain 'reboot' — did not work on lab box)
  5. Wait for boot, zap channel, verify PLAY + vdec00

Usage:
  python tools/av_recovery_run.py
  python tools/av_recovery_run.py --deploy-only
  python tools/av_recovery_run.py --host 192.168.100.102 --zap-ref '1:0:2:82:...'
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import socket
import subprocess
import sys
import time

DEFAULT_HOST = "192.168.100.102"
PORT = 23
USER = "root"
PASS = "root"

# Iran International HD — Badr 26.0E, TP 12265V (lamedb sid 0x82, stype 2)
DEFAULT_ZAP_REF = "1:0:2:82:2:1:1042FE9:0:0:0:"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
PATCH_BIANBIANG = os.path.join(ROOT, "patches", "usr", "bin", "bianbiang.sh")
PATCH_SYSCTL = os.path.join(ROOT, "patches", "etc", "sysctl.conf")
LIVE_PROG_BACKUP = "/data/live_prog_usals_ok.bak"


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


class Telnet:
    def __init__(self, host: str):
        self.host = host
        self.s = None
        self._idx = 0

    def connect(self, timeout=10):
        self.s = socket.create_connection((self.host, PORT), timeout=timeout)
        d = recv_until(self.s, [b"login:", b"ogin:"], 8)
        strip_iac(self.s, d)
        self.s.sendall(USER.encode() + b"\r\n")
        d = recv_until(self.s, [b"assword:"], 6)
        strip_iac(self.s, d)
        self.s.sendall(PASS.encode() + b"\r\n")
        d = recv_until(self.s, [b"# ", b"~#", b"incorrect"], 8)
        if b"incorrect" in d.lower():
            raise RuntimeError("login failed")
        self.s.sendall(b"export PS1='PROMPT> '\r\n")
        recv_until(self.s, [b"PROMPT> "], 5)

    def run(self, cmd, timeout=120):
        self._idx += 1
        token = "MK%dEND" % self._idx
        marker = token.encode()
        self.s.sendall(cmd.encode() + b"\r\n")
        self.s.sendall(('echo "MK""%d""END"' % self._idx).encode() + b"\r\n")
        d = recv_until(self.s, [marker], timeout)
        d = strip_iac(self.s, d)
        txt = d.decode(errors="replace")
        keep = []
        for ln in txt.splitlines():
            st = ln.strip()
            if cmd.strip() and cmd.strip() in ln:
                continue
            if token in ln or ('echo "MK""%d""END"' % self._idx) in ln:
                continue
            if st == "PROMPT>" or st.endswith("PROMPT>"):
                continue
            keep.append(ln)
        return "\n".join(keep).strip("\n")

    def close(self):
        if self.s:
            try:
                self.s.sendall(b"exit\r\n")
            except Exception:
                pass
            try:
                self.s.close()
            except Exception:
                pass
            self.s = None


def wait_telnet(host: str, max_wait=180) -> bool:
    t0 = time.time()
    while time.time() - t0 < max_wait:
        try:
            t = Telnet(host)
            t.connect(timeout=8)
            up = t.run("cat /proc/uptime | cut -d. -f1", 10)
            t.close()
            print("  telnet back, uptime=%ss" % up.strip(), flush=True)
            if up.strip().isdigit() and int(up.strip()) < 600:
                return True
            # still up but maybe not rebooted yet — keep waiting if we expect reboot
        except Exception:
            pass
        time.sleep(5)
    return False


def parse_stat(text: str) -> dict:
    out = {}
    for ln in text.splitlines():
        if "=" not in ln:
            continue
        k, _, v = ln.partition("=")
        k = k.strip()
        v = v.strip()
        try:
            out[k] = int(v)
        except ValueError:
            out[k] = v
    return out


def check_av(t: Telnet) -> dict:
    vdec = t.run("test -e /proc/msp/vdec00 && echo VDEC_OK || echo NO_VDEC", 10)
    avplay = t.run(
        "head -c 4096 /proc/msp/avplay00 2>&1 | grep -E 'CurStatus|Vid Enable|VidPid|Aud Enable' | head -5",
        15,
    )
    vpss = t.run("grep ProcessHZ /proc/msp/vpss01 2>/dev/null | head -1", 10)
    stat = parse_stat(
        t.run("grep -E 'STREAMIN|FRAMEDECED|LOCKED|VSTOP' /proc/msp/stat 2>/dev/null", 15)
    )
    play = "CurStatus" in avplay and "PLAY" in avplay.split("CurStatus", 1)[-1][:24]
    stop = "STOP" in avplay and not play
    healthy = "VDEC_OK" in vdec and play and not stop
    if not healthy and "VDEC_OK" in vdec and "Vid Enable" in avplay and "TRUE" in avplay:
        healthy = True
    return {
        "healthy": healthy,
        "vdec": vdec,
        "avplay_snip": avplay.replace("\n", " | "),
        "vpss": vpss,
        "stat": stat,
    }


def zap_and_wait(t: Telnet, zap_ref: str, wait_sec: int):
    url = "http://127.0.0.1/web/zap?sRef=%s" % zap_ref
    print("ZAP %s" % zap_ref, flush=True)
    t.run("wget -qO- '%s' >/dev/null 2>&1 || true" % url, 30)
    print("  waiting %ds for tune/motor..." % wait_sec, flush=True)
    time.sleep(wait_sec)


def push_file(t: Telnet, local_path: str, remote_path: str, mode="755") -> bool:
    with open(local_path, "rb") as f:
        raw = f.read().replace(b"\r\n", b"\n")
    md5 = hashlib.md5(raw).hexdigest()
    b64 = base64.b64encode(raw).decode()
    tmp = "/tmp/push_%s.b64" % os.path.basename(remote_path)
    t.run("rm -f %s %s" % (tmp, remote_path), 15)
    chunk = 1800
    for i in range(0, len(b64), chunk):
        t.run("printf '%%s' '%s' >> %s" % (b64[i : i + chunk], tmp), 30)
    t.run("base64 -d %s > %s" % (tmp, remote_path), 30)
    t.run("chmod %s %s" % (mode, remote_path), 10)
    remote_md5 = t.run("md5sum %s" % remote_path, 15).split()
    remote_md5 = remote_md5[0] if remote_md5 else "?"
    ok = md5 == remote_md5
    print("  push %s md5=%s %s" % (remote_path, md5[:8], "OK" if ok else "FAIL"), flush=True)
    return ok


def deploy_patches(t: Telnet, host: str) -> None:
    print("=== deploy patches (bianbiang.sh + sysctl + freeze_watch) ===", flush=True)
    t.run(
        "cp /usr/bin/bianbiang.sh /data/bianbiang.sh.bak 2>/dev/null; "
        "cp /etc/sysctl.conf /data/sysctl.conf.bak 2>/dev/null; true",
        15,
    )
    push_file(t, PATCH_BIANBIANG, "/usr/bin/bianbiang.sh")
    push_file(t, PATCH_SYSCTL, "/etc/sysctl.conf", mode="644")
    t.run("sysctl -p /etc/sysctl.conf 2>/dev/null || true", 20)
    loops = t.run("grep -c 'while true' /usr/bin/bianbiang.sh", 10)
    print("  bianbiang respawn loops:", loops, flush=True)
    deploy_watch = os.path.join(HERE, "deploy_freeze_watch.py")
    if os.path.isfile(deploy_watch):
        print("  deploy freeze_watch...", flush=True)
        env = os.environ.copy()
        subprocess.run(
            [sys.executable, deploy_watch],
            env=env,
            check=False,
        )


def force_reboot(t: Telnet) -> None:
    print("=== backup live_prog + /sbin/reboot -f ===", flush=True)
    t.run("cp /data/gx/live_prog %s 2>/dev/null; sync" % LIVE_PROG_BACKUP, 20)
    try:
        t.run("/sbin/reboot -f", 5)
    except Exception:
        pass
    t.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Recover wedged A/V on Spider VIP via Telnet")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--zap-ref", default=DEFAULT_ZAP_REF)
    ap.add_argument("--wait", type=int, default=50, help="seconds after zap")
    ap.add_argument("--deploy-only", action="store_true", help="push patches only, no reboot")
    ap.add_argument("--skip-deploy", action="store_true", help="skip patch deploy")
    ap.add_argument("--skip-reboot", action="store_true", help="probe/zap only")
    args = ap.parse_args()

    print("=== A/V recovery (%s) ===" % args.host, flush=True)
    t = Telnet(args.host)
    t.connect()
    print("LOGIN OK", flush=True)

    if not args.skip_deploy:
        deploy_patches(t, args.host)

    if args.deploy_only:
        t.close()
        print("deploy-only done", flush=True)
        return 0

    r = check_av(t)
    print("AV before recovery:", r, flush=True)

    if r["healthy"]:
        print("A/V already healthy — no reboot needed", flush=True)
        t.close()
        return 0

    if args.skip_reboot:
        zap_and_wait(t, args.zap_ref, args.wait)
        r = check_av(t)
        t.close()
        print("AV after zap:", r, flush=True)
        return 0 if r["healthy"] else 2

    force_reboot(t)

    if not wait_telnet(args.host, 180):
        print("ERROR: box did not return on telnet after reboot", flush=True)
        return 1

    print("=== post-reboot boot wait 90s ===", flush=True)
    time.sleep(90)

    t = Telnet(args.host)
    t.connect()
    zap_and_wait(t, args.zap_ref, args.wait)
    r = check_av(t)
    print("AV after reboot+zap:", r, flush=True)
    t.close()

    if r["healthy"]:
        print("SUCCESS: A/V recovered", flush=True)
        return 0
    print("PARTIAL: check USALS/motor on Badr and retry zap", flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(main())
