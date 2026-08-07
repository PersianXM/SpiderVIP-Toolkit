#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# push build/grab_fb1.py to the device, run it, pull back the PNG of fb1's
# top strip so we can visually confirm the debug bar rendered. Also pushes the
# config and restarts the daemon so the run is representative.
import socket, time, os, base64, re

HOST="192.168.100.102"; PORT=23; USER="root"; PASS="root"
HERE=os.path.dirname(os.path.abspath(__file__))
GRAB=os.path.join(HERE,"..","build","grab_fb1.py")
CONF=os.path.join(HERE,"..","patches","data","dbgbar.conf")
OUT_PNG=os.path.join(HERE,"..","build","dbgbar_fb1.png")

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

def run(s, cmd, timeout=90):
    tok="ZZ%dZZ"%int(time.time()*1000%1000000)
    s.sendall(cmd.encode()+b"\r\n")
    s.sendall(("echo %s"%tok).encode()+b"\r\n")
    d=recv_until(s,[tok.encode()],timeout)
    d=strip_iac(s,d)
    txt=d.decode(errors="replace")
    keep=[]
    for ln in txt.splitlines():
        if tok in ln: continue
        if ("echo %s"%tok) in ln: continue
        keep.append(ln)
    return "\n".join(keep)

def push_text(s, local, remote):
    with open(local,"rb") as f: raw=f.read()
    b64=base64.b64encode(raw).decode()
    run(s,"rm -f %s.b64 %s"%(remote,remote),10)
    for i in range(0,len(b64),2048):
        run(s,"printf '%%s' '%s' >> %s.b64"%(b64[i:i+2048],remote),15)
    run(s,"base64 -d %s.b64 > %s"%(remote,remote),15)

def main():
    print("connecting ...",flush=True); s=login(); print("LOGIN OK",flush=True)
    print("push config + grab script ...",flush=True)
    push_text(s, CONF, "/data/dbgbar.conf")
    push_text(s, GRAB, "/tmp/grab_fb1.py")
    print("restart daemon ...",flush=True)
    run(s,"kill $(pidof dbgbar) 2>/dev/null; sleep 1; /usr/local/dbgbar/dbgbar & echo up",15)
    time.sleep(4)
    print("pidof:", run(s,"pidof dbgbar",10).strip())
    print("run grab ...",flush=True)
    print(run(s,"python3 /tmp/grab_fb1.py 2>&1",60))
    print("pull png ...",flush=True)
    data=run(s,"cat /tmp/dbgbar_png.b64",60)
    blob="".join(re.findall(r"[A-Za-z0-9+/=]", data))
    # trim to valid length
    try:
        png=base64.b64decode(blob+ "="*(-len(blob)%4))
        with open(OUT_PNG,"wb") as f: f.write(png)
        print("SAVED",OUT_PNG,len(png),"bytes")
    except Exception as e:
        print("decode failed",e,"len",len(blob))
    try: s.sendall(b"exit\r\n")
    except Exception: pass
    s.close(); print("DONE")

if __name__=="__main__":
    main()
