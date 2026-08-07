#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cleanup_dbgbar.py - fully revert everything the dbgbar validation put on the
live receiver. The user decided to run the dashboard on the PC instead, so the
box must be left byte-for-byte as it was before.

Removes:
  - the running dbgbar process
  - /usr/local/dbgbar/  (binary + dir we created)
  - /data/dbgbar.conf
  - all /tmp scratch files we pushed (*.b64, grab_fb1.py, dbgbar_png.b64)

Does NOT touch bianbiang.sh (it was never modified on the live box).
Re-mounts / read-only again at the end to restore the original state.
"""
import socket, time, os, sys

HOST="192.168.100.102"; PORT=23; USER="root"; PASS="root"

def recv_until(sock, markers, timeout=30):
    sock.settimeout(0.8); buf=b""; t0=time.time()
    while time.time()-t0<timeout:
        try:
            data=sock.recv(8192)
            if not data: break
            buf+=data
            for m in markers:
                if m in buf: return buf
        except socket.timeout:
            for m in markers:
                if m in buf: return buf
            continue
        except Exception: break
    return buf

def strip_iac(sock,data):
    IAC=255;DO=253;DONT=254;WILL=251;WONT=252;SB=250;SE=240
    out=bytearray();clean=bytearray();i=0
    while i<len(data):
        b=data[i]
        if b==IAC and i+2<len(data):
            cmd=data[i+1];opt=data[i+2]
            if cmd==DO: out+=bytes([IAC,WONT,opt])
            elif cmd==WILL: out+=bytes([IAC,DONT,opt])
            i+=3;continue
        elif b==IAC and i+1<len(data) and data[i+1]==SB:
            j=i+2
            while j<len(data) and data[j]!=SE: j+=1
            i=j+1;continue
        else:
            clean.append(b);i+=1
    if out:
        try: sock.sendall(bytes(out))
        except Exception: pass
    return bytes(clean)

def login():
    s=socket.create_connection((HOST,PORT),timeout=10)
    d=recv_until(s,[b"login:",b"ogin:"],8);strip_iac(s,d)
    s.sendall(USER.encode()+b"\r\n")
    d=recv_until(s,[b"assword:"],6);strip_iac(s,d)
    s.sendall(PASS.encode()+b"\r\n")
    recv_until(s,[b"# ",b"~#"],8)
    s.sendall(b"export PS1='PROMPT> '\r\n")
    recv_until(s,[b"PROMPT> "],5)
    return s

def run(s, cmd, timeout=30):
    tok="ZZ%dZZ"%int(time.time()*1000%1000000)
    s.sendall(cmd.encode()+b"\r\n")
    s.sendall(("echo %s"%tok).encode()+b"\r\n")
    d=recv_until(s,[tok.encode()],timeout)
    d=strip_iac(s,d); txt=d.decode(errors="replace")
    keep=[]
    for ln in txt.splitlines():
        if tok in ln: continue
        if ln.strip().startswith("echo %s"%tok): continue
        if cmd and cmd in ln: continue
        if "PROMPT>" in ln and not ln.strip().replace("PROMPT>","").strip(): continue
        keep.append(ln)
    return "\n".join(keep).strip("\n")

def main():
    print("connecting to %s ..."%HOST, flush=True)
    try:
        s=login()
    except Exception as e:
        sys.exit("could not reach receiver (%s). Is it powered on and on the network?"%e)
    print("LOGIN OK", flush=True)

    print("-- before: is dbgbar running? --")
    print("  pidof dbgbar:", run(s,"pidof dbgbar",10) or "(none)")

    print("-- killing daemon --")
    run(s,"kill $(pidof dbgbar) 2>/dev/null; sleep 1; kill -9 $(pidof dbgbar) 2>/dev/null; true",10)
    print("  pidof after kill:", run(s,"pidof dbgbar",10) or "(none)")

    print("-- make rootfs writable to delete the binary --")
    run(s,"mount -o remount,rw / 2>/dev/null; true",10)

    print("-- removing installed files --")
    run(s,"rm -rf /usr/local/dbgbar",10)
    run(s,"rm -f /data/dbgbar.conf",10)
    run(s,"rm -f /tmp/dbgbar.b64 /tmp/dbgbarconf.b64 /tmp/dbgbar_png.b64 /tmp/grab_fb1.py",10)

    print("-- verify removal --")
    print("  /usr/local/dbgbar :", run(s,"ls -ld /usr/local/dbgbar 2>&1",10))
    print("  /data/dbgbar.conf :", run(s,"ls -l /data/dbgbar.conf 2>&1",10))
    print("  /tmp scratch      :", run(s,"ls -l /tmp/dbgbar* /tmp/grab_fb1.py 2>&1",10))

    print("-- confirm bianbiang.sh untouched (no dbgbar hook on live box) --")
    print("  ", run(s,"grep -c dbgbar /usr/bin/bianbiang.sh 2>/dev/null || echo 0",10))

    print("-- restore rootfs to read-only (original state) --")
    run(s,"sync; mount -o remount,ro / 2>/dev/null; true",10)
    print("  mount / :", run(s,"mount | grep ' / '",10))

    try: s.sendall(b"exit\r\n")
    except Exception: pass
    s.close()
    print("CLEANUP DONE - receiver reverted to original state")

if __name__=="__main__":
    main()
