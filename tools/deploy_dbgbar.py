#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy_dbgbar.py - push the cross-compiled dbgbar ARM binary + config to the
receiver over telnet, install to /usr/local/dbgbar, start it, and verify it is
running and drawing (checks pidof + that fb1 got non-zero pixels).

Safe & reversible:
  - installs into a NEW path /usr/local/dbgbar (touches nothing existing)
  - config to /data/dbgbar.conf
  - does NOT modify bianbiang.sh on the live box (that hook is for the baked
    firmware image); here we just launch the daemon directly for validation.
"""
import socket, time, os, base64, hashlib, sys

HOST="192.168.100.102"; PORT=23; USER="root"; PASS="root"
HERE=os.path.dirname(os.path.abspath(__file__))
BIN=os.path.join(HERE,"..","patches","usr","local","dbgbar","dbgbar")
CONF=os.path.join(HERE,"..","patches","data","dbgbar.conf")

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

def run(s, cmd, timeout=60):
    tok="ZZ%dZZ"%int(time.time()*1000%1000000)
    s.sendall(cmd.encode()+b"\r\n")
    s.sendall(("echo %s"%tok).encode()+b"\r\n")
    d=recv_until(s,[tok.encode()],timeout)
    d=strip_iac(s,d)
    txt=d.decode(errors="replace")
    keep=[]
    for ln in txt.splitlines():
        if tok in ln: continue
        if ln.strip().startswith("echo %s"%tok): continue
        if cmd and cmd in ln: continue
        if "PROMPT>" in ln and not ln.strip().replace("PROMPT>","").strip(): continue
        keep.append(ln)
    return "\n".join(keep).strip("\n")

def push_b64(s, local_path, remote_b64, remote_final, decode=True):
    with open(local_path,"rb") as f:
        raw=f.read()
    md5=hashlib.md5(raw).hexdigest()
    b64=base64.b64encode(raw).decode()
    run(s,"rm -f %s %s"%(remote_b64, remote_final),15)
    CH=2048
    n=(len(b64)+CH-1)//CH
    for i in range(0,len(b64),CH):
        part=b64[i:i+CH]
        run(s,"printf '%%s' '%s' >> %s"%(part, remote_b64),20)
        print("\r  %s: chunk %d/%d"%(os.path.basename(local_path), i//CH+1, n),end="",flush=True)
    print()
    if decode:
        run(s,"base64 -d %s > %s"%(remote_b64, remote_final),30)
    return md5

def main():
    if not os.path.exists(BIN):
        sys.exit("binary not found: %s (build first)"%BIN)
    print("connecting to %s ..."%HOST,flush=True)
    s=login()
    print("LOGIN OK",flush=True)

    print("-- pre-flight: writable rootfs? --")
    print(run(s,"mount | grep ' / '",10))
    run(s,"mount -o remount,rw / 2>/dev/null; mkdir -p /usr/local/dbgbar",15)

    print("-- pushing binary (%d bytes) --"%os.path.getsize(BIN))
    md5=push_b64(s, BIN, "/tmp/dbgbar.b64", "/usr/local/dbgbar/dbgbar")
    run(s,"chmod +x /usr/local/dbgbar/dbgbar",10)
    dev_md5=run(s,"md5sum /usr/local/dbgbar/dbgbar",15).split()[0] if run(s,"md5sum /usr/local/dbgbar/dbgbar",15) else "?"
    print("host md5=%s  device md5=%s  %s"%(md5, dev_md5, "MATCH" if md5==dev_md5 else "MISMATCH"))

    print("-- pushing config --")
    push_b64(s, CONF, "/tmp/dbgbarconf.b64", "/data/dbgbar.conf")

    print("-- file listing --")
    print(run(s,"ls -l /usr/local/dbgbar/dbgbar /data/dbgbar.conf",10))

    print("-- launch daemon --")
    run(s,"kill $(pidof dbgbar) 2>/dev/null; sleep 1",10)
    run(s,"/usr/local/dbgbar/dbgbar & echo started",10)
    time.sleep(3)
    print("pidof:", run(s,"pidof dbgbar",10))
    print("-- process stats --")
    print(run(s,"cat /proc/$(pidof dbgbar)/status 2>/dev/null | grep -E 'VmRSS|State|Threads'",10))
    print("-- fb1 non-zero check (top strip) --")
    print(run(s,"dd if=/dev/fb1 bs=4096 count=1 2>/dev/null | od -An -tx1 | grep -v '00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00' | head -3",15))
    print("-- temp read sanity --")
    print(run(s,"cat /proc/hisi/msp/chip_temp 2>/dev/null | head -2",10))

    try: s.sendall(b"exit\r\n")
    except Exception: pass
    s.close()
    print("DEPLOY DONE")

if __name__=="__main__":
    main()
