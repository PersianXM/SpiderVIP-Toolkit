#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grab_and_pull.py - push dev_grab.py to the receiver, run it (inject VOLUME key,
grab framebuffer, encode small PNG), then pull /tmp/volbar.b64 back and decode
it into build/volbar.png so we can SEE the on-screen volume bar.
"""
import socket, time, sys, os, base64

HOST="192.168.100.102"; PORT=23; USER="root"; PASS="root"
HERE=os.path.dirname(os.path.abspath(__file__))
DEV_SCRIPT=os.path.join(HERE,"..","build","dev_grab.py")
OUT_PNG=os.path.join(HERE,"..","build","volbar.png")

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
    tok="ZZ%dZZ"%int(time.time()%100000)
    s.sendall(cmd.encode()+b"\r\n")
    s.sendall(("echo %s"%tok).encode()+b"\r\n")
    d=recv_until(s,[tok.encode()],timeout)
    d=strip_iac(s,d)
    return d.decode(errors="replace")

def main():
    with open(DEV_SCRIPT,"r",encoding="utf-8") as f:
        script=f.read()
    b64=base64.b64encode(script.encode()).decode()
    print("connecting ...",flush=True)
    s=login()
    print("LOGIN OK",flush=True)
    # push script in chunks to avoid overly long lines
    run(s,"rm -f /tmp/grab.b64 /tmp/grab.py /tmp/volbar.b64",10)
    CH=1024
    for i in range(0,len(b64),CH):
        part=b64[i:i+CH]
        run(s,"printf '%%s' '%s' >> /tmp/grab.b64"%part,15)
    run(s,"base64 -d /tmp/grab.b64 > /tmp/grab.py",10)
    print("script pushed, running grab ...",flush=True)
    out=run(s,"python3 /tmp/grab.py 2>&1",60)
    print("---DEVICE OUTPUT---")
    print(out)
    # pull the b64 png
    print("pulling image ...",flush=True)
    data=run(s,"cat /tmp/volbar.b64",60)
    # extract the base64 blob: keep only base64 chars between our echoes
    lines=data.splitlines()
    blob="".join(ln.strip() for ln in lines
                 if ln.strip() and "PROMPT>" not in ln
                 and "cat /tmp/volbar.b64" not in ln
                 and "ZZ" not in ln)
    # keep valid base64 chars
    import re
    blob="".join(re.findall(r"[A-Za-z0-9+/=]", blob))
    try:
        png=base64.b64decode(blob)
        with open(OUT_PNG,"wb") as f:
            f.write(png)
        print("SAVED", OUT_PNG, len(png), "bytes")
    except Exception as e:
        print("decode failed:", e, "blob len", len(blob))
    try: s.sendall(b"exit\r\n")
    except Exception: pass
    s.close()
    print("DONE")

if __name__=="__main__":
    main()
