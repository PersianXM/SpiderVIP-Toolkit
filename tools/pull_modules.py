#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pull_modules.py - reliably base64-pull kernel .ko modules from the receiver to
local build/modules/ for offline disassembly (device has no objdump).

Method: on the device, base64 the .ko into a temp file, wrap the cat between two
unique markers, and validate the decoded bytes against the device-side md5sum.
"""
import socket, time, os, base64, re, hashlib

HOST="192.168.100.102"; PORT=23; USER="root"; PASS="root"
HERE=os.path.dirname(os.path.abspath(__file__))
OUTDIR=os.path.join(HERE,"..","build","modules")
os.makedirs(OUTDIR, exist_ok=True)

FILES=[
    "/lib/modules/4.4.176/extra/usb_f_service.ko",
    "/lib/modules/4.4.176/extra/libcomposite.ko",
    "/lib/modules/4.4.176/extra/udc-hisi.ko",
    "/lib/modules/4.4.176/extra/g_service.ko",
]

def recv_until(sock, markers, timeout=120):
    sock.settimeout(0.8); buf=b""; t0=time.time()
    while time.time()-t0<timeout:
        try:
            data=sock.recv(65536)
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

def run(s, cmd, timeout=120):
    s.sendall(cmd.encode()+b"\r\n")
    d=recv_until(s,[b"PROMPT> "],timeout)
    d=strip_iac(s,d)
    return d.decode(errors="replace")

def pull_one(s, path):
    name=os.path.basename(path)
    # device-side md5 for validation
    md5line=run(s,"md5sum %s"%path,30)
    m=re.search(r"([0-9a-f]{32})", md5line)
    want_md5=m.group(1) if m else None
    # base64 into a temp file, then cat between unique markers
    B="B64_%d_START"%int(time.time()*1000%1000000)
    E="B64_END_TOKEN"
    run(s,"base64 %s > /tmp/mod.b64"%path,60)
    raw=run(s,"echo %s; cat /tmp/mod.b64; echo %s"%(B,E),120)
    # slice strictly between the markers
    if B not in raw or E not in raw:
        print("  MARKER MISS for",name); return
    body=raw.split(B,1)[1].split(E,1)[0]
    blob="".join(re.findall(r"[A-Za-z0-9+/=]", body))
    # fix padding just in case
    pad=len(blob)%4
    if pad: blob=blob+"="*(4-pad)
    try:
        data=base64.b64decode(blob)
    except Exception as e:
        print("  decode failed:",e,"blob",len(blob)); return
    got_md5=hashlib.md5(data).hexdigest()
    ok = (want_md5 is None) or (got_md5==want_md5)
    dst=os.path.join(OUTDIR,name)
    with open(dst,"wb") as f: f.write(data)
    print("  SAVED %s (%d bytes) md5=%s %s"%(
        name,len(data),got_md5,
        "OK" if ok else "MISMATCH(want %s)"%want_md5))

def main():
    s=login(); print("LOGIN OK",flush=True)
    for p in FILES:
        print("pulling",os.path.basename(p),"...",flush=True)
        pull_one(s,p)
    try: s.sendall(b"exit\r\n")
    except Exception: pass
    s.close(); print("DONE")

if __name__=="__main__":
    main()
