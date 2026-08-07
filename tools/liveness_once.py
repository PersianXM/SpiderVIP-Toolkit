#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""liveness_once.py — ONE gentle telnet connect, short timeout, minimal command.
Just determines if the box is still alive after the rmmod g_service test.
No retries, no heavy commands. If it can't connect => box is wedged => power-cycle."""
import socket, sys

HOST="192.168.100.102"; PORT=23; USER="root"; PASS="root"

def recv_until(s, markers, timeout=6):
    import time
    s.settimeout(0.5); buf=b""; t0=time.time()
    while time.time()-t0<timeout:
        try:
            d=s.recv(4096)
            if not d: break
            buf+=d
            for m in markers:
                if m in buf: return buf
        except socket.timeout:
            for m in markers:
                if m in buf: return buf
        except Exception: break
    return buf

def main():
    try:
        s=socket.create_connection((HOST,PORT),timeout=6)
    except Exception as e:
        print(f"DEAD: cannot connect ({e}) -> box is hung, please power-cycle")
        sys.exit(1)
    try:
        recv_until(s,[b"ogin:"],6); s.sendall(USER.encode()+b"\r\n")
        recv_until(s,[b"assword:"],5); s.sendall(PASS.encode()+b"\r\n")
        recv_until(s,[b"# ",b"~#"],6)
        s.sendall(b"echo ALIVE_$(cat /proc/uptime | cut -d. -f1)s\r\n")
        out=recv_until(s,[b"ALIVE_"],6).decode(errors="replace")
        print("LIVE:", "ALIVE_" in out, "\n", out[-200:])
        s.sendall(b"exit\r\n"); s.close()
    except Exception as e:
        print(f"CONNECTED-BUT-UNRESPONSIVE: {e} -> likely wedged, power-cycle")
        sys.exit(2)

if __name__=="__main__":
    main()
