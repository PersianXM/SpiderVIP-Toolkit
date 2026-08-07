#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ensure_gadget_up.py — resilient rollback confirmer.
Retries the telnet connection (device has few slots) until it gets in, then
runs `gadgetctl up` (idempotent) and prints the module state to PROVE the
lazy prototype is fully reversible and Live-TV transport is intact.
"""
import socket, time

HOST="192.168.100.102"; PORT=23; USER="root"; PASS="root"

def recv_until(s, markers, timeout=30):
    s.settimeout(0.6); buf=b""; t0=time.time()
    while time.time()-t0<timeout:
        try:
            d=s.recv(65536)
            if not d: break
            buf+=d
            for m in markers:
                if m in buf: return buf
        except socket.timeout:
            for m in markers:
                if m in buf: return buf
        except Exception: break
    return buf

def strip_iac(s,data):
    IAC=255;DO=253;DONT=254;WILL=251;WONT=252;SB=250;SE=240
    out=bytearray();clean=bytearray();i=0
    while i<len(data):
        b=data[i]
        if b==IAC and i+2<len(data):
            c=data[i+1];o=data[i+2]
            if c==DO: out+=bytes([IAC,WONT,o])
            elif c==WILL: out+=bytes([IAC,DONT,o])
            i+=3;continue
        elif b==IAC and i+1<len(data) and data[i+1]==SB:
            j=i+2
            while j<len(data) and data[j]!=SE: j+=1
            i=j+1;continue
        else: clean.append(b);i+=1
    if out:
        try: s.sendall(bytes(out))
        except Exception: pass
    return bytes(clean)

def connect_retry(tries=40, delay=5):
    for k in range(tries):
        try:
            s=socket.create_connection((HOST,PORT),timeout=8)
            return s
        except Exception as e:
            print(f"[{k+1}/{tries}] no slot yet ({e}); waiting {delay}s...",flush=True)
            time.sleep(delay)
    raise SystemExit("could not get a telnet slot")

def run(s,cmd,t=30):
    s.sendall(cmd.encode()+b"\r\n")
    return strip_iac(s,recv_until(s,[b"PROMPT> "],t)).decode(errors="replace")

def main():
    s=connect_retry()
    strip_iac(s,recv_until(s,[b"ogin:"],8)); s.sendall(USER.encode()+b"\r\n")
    strip_iac(s,recv_until(s,[b"assword:"],6)); s.sendall(PASS.encode()+b"\r\n")
    recv_until(s,[b"# ",b"~#"],8)
    s.sendall(b"export PS1='PROMPT> '\r\n"); recv_until(s,[b"PROMPT> "],5)
    print("LOGIN OK",flush=True)
    print(run(s,"gadgetctl up",15))
    print(run(s,"gadgetctl status",10))
    print(run(s,"lsmod | grep -E 'g_service|u_service|usb_f_service|libcomposite'",10))
    print(run(s,"lsmod | grep -E 'hi_dvb|hi_demux|vtunerc|hisi_sci'",10))
    try: s.sendall(b"exit\r\n")
    except Exception: pass
    s.close(); print("DONE")

if __name__=="__main__":
    main()
