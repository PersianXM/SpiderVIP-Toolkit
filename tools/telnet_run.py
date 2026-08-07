#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telnet_run.py - login to the receiver (root/root) and run a batch of shell
commands read from a UTF-8 file (one command per line; blank lines and lines
starting with '#' are skipped). Prints each command's output. ASCII-safe.

Usage:  python telnet_run.py <commands_file>
"""
import socket, time, sys

HOST = "192.168.100.102"
PORT = 23
USER = "root"
PASS = "root"

def recv_until(sock, markers, timeout=8):
    sock.settimeout(0.8)
    buf = b""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            data = sock.recv(4096)
            if not data:
                break
            buf += data
            for m in markers:
                if m in buf:
                    return buf
        except socket.timeout:
            for m in markers:
                if m in buf:
                    return buf
            continue
        except Exception:
            break
    return buf

def strip_iac(sock, data):
    IAC=255; DO=253; DONT=254; WILL=251; WONT=252; SB=250; SE=240
    out=bytearray(); clean=bytearray(); i=0
    while i < len(data):
        b=data[i]
        if b==IAC and i+2 < len(data):
            cmd=data[i+1]; opt=data[i+2]
            if cmd==DO: out+=bytes([IAC,WONT,opt])
            elif cmd==WILL: out+=bytes([IAC,DONT,opt])
            i+=3; continue
        elif b==IAC and i+1 < len(data) and data[i+1] in (SB,):
            j=i+2
            while j < len(data) and data[j]!=SE: j+=1
            i=j+1; continue
        else:
            clean.append(b); i+=1
    if out:
        try: sock.sendall(bytes(out))
        except Exception: pass
    return bytes(clean)

def login():
    s = socket.create_connection((HOST, PORT), timeout=10)
    d = recv_until(s, [b"login:", b"ogin:"], 8); strip_iac(s, d)
    s.sendall(USER.encode()+b"\r\n")
    d = recv_until(s, [b"assword:"], 6); strip_iac(s, d)
    s.sendall(PASS.encode()+b"\r\n")
    d = recv_until(s, [b"# ", b"#\r", b"~#", b"incorrect"], 8)
    txt = d.decode(errors="replace")
    if "incorrect" in txt.lower():
        raise RuntimeError("login incorrect")
    s.sendall(b"export PS1='PROMPT> '\r\n")
    recv_until(s, [b"PROMPT> "], 5)
    return s

def run(s, cmd, idx, timeout=180):
    # marker whose command-echo differs from its stdout, so the echoed
    # 'echo' line cannot false-match the completion marker.
    token = "MK%dEND" % idx
    marker = token.encode()
    s.sendall(cmd.encode()+b"\r\n")
    s.sendall(('echo "MK""%d""END"' % idx).encode()+b"\r\n")
    d = recv_until(s, [marker], timeout)
    d = strip_iac(s, d)
    txt = d.decode(errors="replace")
    keep = []
    for ln in txt.splitlines():
        st = ln.strip()
        if cmd.strip() and cmd.strip() in ln:
            continue
        if ('echo "MK""%d""END"' % idx) in ln:
            continue
        if token in ln:
            continue
        if st == "PROMPT>" or st.endswith("PROMPT>"):
            continue
        keep.append(ln)
    return "\n".join(keep).strip("\n")

def main():
    if len(sys.argv) < 2:
        print("usage: telnet_run.py <commands_file>"); return
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        cmds = [l.rstrip("\n") for l in f]
    cmds = [c for c in cmds if c.strip() and not c.lstrip().startswith("#")]
    print("connecting to %s ..." % HOST, flush=True)
    s = login()
    print("LOGIN OK\n", flush=True)
    for i, c in enumerate(cmds):
        print("==== [%d] %s" % (i, c), flush=True)
        out = run(s, c, i)
        print(out, flush=True)
        print("", flush=True)
    try: s.sendall(b"exit\r\n")
    except Exception: pass
    s.close()
    print("==== DONE ====", flush=True)

if __name__ == "__main__":
    main()
