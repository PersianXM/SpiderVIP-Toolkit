#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Pull an already-generated base64 PNG (/tmp/dbgbar_png.b64) off the receiver
# cleanly and write build/dbgbar_fb1.png. Uses a sentinel-delimited cat so we
# capture only the base64 blob.
import socket, time, os, base64, re

HOST="192.168.100.102"; PORT=23; USER="root"; PASS="root"
HERE=os.path.dirname(os.path.abspath(__file__))
OUT_PNG=os.path.join(HERE,"..","build","dbgbar_fb1.png")

def recv_until(sock, markers, timeout=40):
    sock.settimeout(0.8); buf=b""; t0=time.time()
    while time.time()-t0<timeout:
        try:
            data=sock.recv(16384)
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

s=login()
print("LOGIN OK")
# regenerate a fresh capture first
s.sendall(b"python3 /tmp/grab_fb1.py 2>&1\r\n")
recv_until(s,[b"WROTE",b"Error",b"Traceback"],40)
# delimited read. Build sentinels at runtime so the echoed command line does
# NOT literally contain the full sentinel (avoids matching the echo itself).
s.sendall(b"S=B64; echo ${S}STA RT | tr -d ' '; cat /tmp/dbgbar_png.b64; echo; echo ${S}EN D | tr -d ' '\r\n")
d=recv_until(s,[b"B64END"],40)
d=strip_iac(s,d).decode(errors="replace")
# take the LAST start marker occurrence (the real output, not any echo)
matches=list(re.finditer(r"B64START(.*?)B64END", d, re.S))
blob=""
if matches:
    blob="".join(re.findall(r"[A-Za-z0-9+/=]", matches[-1].group(1)))
print("blob len", len(blob))
png=base64.b64decode(blob+"="*(-len(blob)%4))
with open(OUT_PNG,"wb") as f: f.write(png)
print("SAVED", OUT_PNG, len(png), "bytes")
print("PNG magic OK" if png[:8]==b"\x89PNG\r\n\x1a\n" else "BAD PNG magic: %r"%png[:8])
try: s.sendall(b"exit\r\n")
except Exception: pass
s.close()
