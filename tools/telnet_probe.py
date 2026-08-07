#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telnet_probe.py - connect to the receiver over Telnet, try common root
passwords, and read real RAM/device info. ASCII-only output.
"""
import socket, time, sys

HOST = "192.168.100.102"
PORT = 23

# common default passwords for these Enigma2 / Chinese STB images
PASSWORDS = ["", "root", "spider", "admin", "password", "1234", "12345678",
             "spider123", "vip", "spidervip", "0000", "1111", "dreambox"]

CMDS = [
    "cat /proc/meminfo | head -4",
    "free -m || free",
    "cat /proc/cmdline",
    "cat /proc/media-mem 2>/dev/null; cat /proc/umap/media-mem 2>/dev/null; cat /proc/mmz_info 2>/dev/null",
    "uname -a",
    "cat /etc/version 2>/dev/null; cat /etc/image-version 2>/dev/null",
    "ls -l /data/raminfo.txt 2>/dev/null; cat /data/raminfo.txt 2>/dev/null",
    "cat /proc/hisi/msp/mmz 2>/dev/null",
]

def recv_until(sock, patterns, timeout=6):
    sock.settimeout(timeout)
    buf = b""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            data = sock.recv(4096)
            if not data:
                break
            buf += data
            low = buf.lower()
            for p in patterns:
                if p in low:
                    return buf, p
        except socket.timeout:
            break
        except Exception:
            break
    return buf, None

def neg(sock, data):
    # minimal telnet option negotiation: refuse everything (WONT/DONT)
    IAC=255; DO=253; DONT=254; WILL=251; WONT=252
    out=bytearray(); i=0
    clean=bytearray()
    while i < len(data):
        b=data[i]
        if b==IAC and i+2 < len(data):
            cmd=data[i+1]; opt=data[i+2]
            if cmd==DO: out+=bytes([IAC,WONT,opt])
            elif cmd==WILL: out+=bytes([IAC,DONT,opt])
            i+=3; continue
        else:
            clean.append(b); i+=1
    if out:
        try: sock.sendall(bytes(out))
        except Exception: pass
    return bytes(clean)

def try_login(pw):
    s = socket.create_connection((HOST, PORT), timeout=8)
    buf, hit = recv_until(s, [b"login:", b"username:"], 8)
    buf = neg(s, buf)
    # re-read after negotiation in case prompt came with options
    if b"login" not in buf.lower():
        more,_ = recv_until(s, [b"login:", b"username:"], 4)
        neg(s, more)
    s.sendall(b"root\r\n")
    buf, hit = recv_until(s, [b"password:"], 6)
    neg(s, buf)
    s.sendall(pw.encode() + b"\r\n")
    # after password: either shell prompt (# or $) or "incorrect"/login again
    buf, hit = recv_until(s, [b"incorrect", b"# ", b"#\r", b"~#", b"login:", b"$ "], 7)
    txt = buf.decode(errors="replace")
    ok = ("incorrect" not in txt.lower()) and ("login:" not in txt.lower()[-40:]) and \
         (("#" in txt) or ("$" in txt) or ("BusyBox" in txt) or ("~" in txt))
    return s, ok, txt

def run_cmd(s, cmd):
    s.sendall(cmd.encode() + b"\r\n")
    buf,_ = recv_until(s, [b"@@DONE@@"], 6)
    s.sendall(b"echo @@DONE@@\r\n")
    buf2,_ = recv_until(s, [b"@@DONE@@"], 6)
    return (buf+buf2).decode(errors="replace")

def main():
    print("target %s:%d" % (HOST, PORT), flush=True)
    for pw in PASSWORDS:
        try:
            print("\n--- trying password: %r ---" % pw, flush=True)
            s, ok, txt = try_login(pw)
            tail = txt[-200:].replace("\r"," ").replace("\n"," ")
            print("   result tail: %s" % tail, flush=True)
            if ok:
                print("\n############ LOGIN OK with password: %r ############\n" % pw, flush=True)
                for c in CMDS:
                    print("\n$ %s" % c, flush=True)
                    out = run_cmd(s, c)
                    # strip the echoed command + DONE marker
                    print(out, flush=True)
                try: s.sendall(b"exit\r\n")
                except Exception: pass
                s.close()
                print("\n==== FINISHED SUCCESSFULLY ====", flush=True)
                return
            s.close()
        except Exception as e:
            print("   error: %s" % e, flush=True)
            time.sleep(0.5)
    print("\nNo password worked from the common list.", flush=True)
    print("Please tell me the device's root password, or set/remove it from the STB menu.", flush=True)

if __name__ == "__main__":
    main()
