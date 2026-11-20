#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy_audio_watch.py - install, remove or check the on-box audio freeze watchdog.

Usage:  python tools/deploy_audio_watch.py [install|remove|status] [--host IP]

install  copies tools/audio_watch.sh to /data/audio_watch, hooks it into
         /home/gx/local/user_script (run by the vendor bianbiang.sh at every
         boot) and starts it now. Safe to repeat; run it again after a
         factory reset or firmware update.
remove   stops it and removes the file and the boot hook.
status   shows whether it runs, the hook, and its recent log.

The receiver is found by trying the known addresses, then by scanning the
PC's /24 for a Telnet banner from host "clap4k". No login is attempted on
any other device.
"""
import argparse
import concurrent.futures
import hashlib
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telnet_run

KNOWN_HOSTS = ["192.168.100.102", "192.168.100.146"]
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_watch.sh")
# The AW_* overrides exist only for the fake-box test.
BOX_DIR = os.environ.get("AW_BOX_DIR", "/data/audio_watch")
BOX_SCRIPT = BOX_DIR + "/audio_watch.sh"
HOOK = os.environ.get("AW_HOOK", "/home/gx/local/user_script")
BOOT_ID = os.environ.get("AW_BOOT_ID", "/proc/sys/kernel/random/boot_id")
HOOK_LINE = "sh %s >/dev/null 2>&1 &  # audio_watch" % BOX_SCRIPT
BANNER = b"clap4k"


def banner_of(host, timeout=1.5):
    try:
        with socket.create_connection((host, 23), timeout=timeout) as sock:
            sock.settimeout(timeout)
            data = b""
            while b"login" not in data and len(data) < 512:
                chunk = sock.recv(256)
                if not chunk:
                    break
                data += chunk
            return data
    except OSError:
        return b""


def local_prefix():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.168.100.1", 9))
        return probe.getsockname()[0].rsplit(".", 1)[0]
    finally:
        probe.close()


def find_receiver(hosts):
    for host in hosts:
        if BANNER in banner_of(host):
            return host
    prefix = local_prefix()
    print("receiver not at %s, scanning %s.0/24 ..." % (", ".join(hosts), prefix), flush=True)
    candidates = ["%s.%d" % (prefix, n) for n in range(1, 255)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        for host, data in zip(candidates, pool.map(lambda h: banner_of(h, 1.0), candidates)):
            if BANNER in data:
                return host
    return None


def run(sock, cmd, timeout=30):
    run.index += 1
    return telnet_run.run(sock, cmd, run.index, timeout=timeout)


run.index = 100


def stop_running(sock):
    """Stop the copy started in this boot. The boot id check keeps a pid left
    from an earlier boot, now reused by another process, from being killed."""
    run(sock, "[ -e %s/pid ] && set -- $(cat %s/pid) && [ \"$2\" = \"$(cat %s)\" ] && kill $1 2>/dev/null; sleep 1"
        % (BOX_DIR, BOX_DIR, BOOT_ID))


def install(sock):
    body = open(SCRIPT, "rb").read().replace(b"\r\n", b"\n")
    digest = hashlib.md5(body).hexdigest()
    run(sock, "set +H 2>/dev/null; mkdir -p %s %s" % (BOX_DIR, os.path.dirname(HOOK)))
    payload = b"cat > %s.new <<'AWEOF'\r\n" % BOX_SCRIPT.encode()
    payload += body.rstrip(b"\n").replace(b"\n", b"\r\n") + b"\r\nAWEOF\r\n"
    sock.sendall(payload)
    telnet_run.recv_until(sock, [b"PROMPT> "], 10)
    got = run(sock, "md5sum %s.new | cut -d' ' -f1" % BOX_SCRIPT).strip().splitlines()
    if not got or got[-1].strip() != digest:
        run(sock, "rm -f %s.new" % BOX_SCRIPT)
        raise RuntimeError("copy check failed (md5 %s, box %s)" % (digest, got[-1] if got else "none"))
    run(sock, "mv %s.new %s && chmod 755 %s" % (BOX_SCRIPT, BOX_SCRIPT, BOX_SCRIPT))
    run(sock, "rm -f %s/disable" % BOX_DIR)
    stop_running(sock)
    run(sock, "[ -e %s ] || printf '#!/bin/sh\\n' > %s" % (HOOK, HOOK))
    run(sock, "grep -q 'audio_watch' %s || echo '%s' >> %s" % (HOOK, HOOK_LINE, HOOK))
    run(sock, "chmod 755 %s" % HOOK)
    run(sock, "( if command -v setsid >/dev/null; then setsid sh %s; else nohup sh %s; fi </dev/null >/dev/null 2>&1 & ) ; sleep 2"
        % (BOX_SCRIPT, BOX_SCRIPT))


def remove(sock):
    run(sock, "set +H 2>/dev/null")
    run(sock, "touch %s/disable 2>/dev/null" % BOX_DIR)
    stop_running(sock)
    run(sock, "[ -e %s ] && sed -i '/audio_watch/d' %s" % (HOOK, HOOK))
    run(sock, "[ -e %s ] && [ \"$(grep -cv '^#!' %s)\" = 0 ] && rm -f %s" % (HOOK, HOOK, HOOK))
    run(sock, "rm -rf %s" % BOX_DIR)


def status(sock):
    text = run(sock, "P=''; [ -e %s/pid ] && set -- $(cat %s/pid) && "
                     "[ \"$2\" = \"$(cat %s)\" ] && kill -0 $1 2>/dev/null && P=$1; "
                     "echo running=${P:-no}; "
                     "grep -c audio_watch %s 2>/dev/null | sed 's/^/hook_lines=/'; "
                     "[ -e %s ] && echo script=yes || echo script=no; "
                     "[ -e %s/disable ] && echo disabled=yes; "
                     "ls %s/event_*.txt 2>/dev/null | wc -l | sed 's/^/auto_reboots_saved=/'; "
                     "tail -n 5 %s/log 2>/dev/null"
               % (BOX_DIR, BOX_DIR, BOOT_ID, HOOK, BOX_SCRIPT, BOX_DIR, BOX_DIR, BOX_DIR))
    print(text)
    return "running=" in text and "running=no" not in text


def main():
    parser = argparse.ArgumentParser(description="Audio freeze watchdog installer")
    parser.add_argument("action", nargs="?", default="install", choices=["install", "remove", "status"])
    parser.add_argument("--host", action="append", help="receiver IP")
    args = parser.parse_args()

    host = find_receiver(args.host or KNOWN_HOSTS)
    if not host:
        print("FAILED: receiver not found on this network. Is it on and connected?")
        return 1
    print("receiver found at %s" % host, flush=True)
    telnet_run.HOST = host
    sock = telnet_run.login()
    try:
        if args.action == "install":
            install(sock)
        elif args.action == "remove":
            remove(sock)
        running = status(sock)
    finally:
        try:
            sock.sendall(b"exit\r\n")
            sock.close()
        except OSError:
            pass
    if args.action == "install":
        print("OK: watchdog installed and running." if running else "FAILED: installed but not running.")
        return 0 if running else 1
    if args.action == "remove":
        print("OK: watchdog removed." if not running else "FAILED: still running.")
        return 0 if not running else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
