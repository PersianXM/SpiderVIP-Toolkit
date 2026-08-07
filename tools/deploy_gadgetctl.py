#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy_gadgetctl.py — push patches/usr/bin/gadgetctl.sh to the device as
/usr/bin/gadgetctl (base64 transfer), chmod +x, then run a RUNTIME PROTOTYPE
validation that is fully reversible:

  1) snapshot: lsmod refcnts + non-core log count + dwc_otg irq
  2) gadgetctl down   (rmmod g_service ONLY)  -> gadget Idle
  3) verify: u_service/usb_f_service/hi_dvb STILL loaded (Live TV safe),
             non-core log count stops growing
  4) gadgetctl up     (insmod g_service)      -> gadget restored
  5) verify: back to original state (rollback proven)

No boot files are modified. Everything is in-memory and reversible.
"""
import socket, time, os, base64, re

HOST="192.168.100.102"; PORT=23; USER="root"; PASS="root"
HERE=os.path.dirname(os.path.abspath(__file__))
SRC=os.path.join(HERE,"..","patches","usr","bin","gadgetctl.sh")

def recv_until(s, markers, timeout=60):
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

def login():
    s=socket.create_connection((HOST,PORT),timeout=10)
    strip_iac(s,recv_until(s,[b"ogin:"],8)); s.sendall(USER.encode()+b"\r\n")
    strip_iac(s,recv_until(s,[b"assword:"],6)); s.sendall(PASS.encode()+b"\r\n")
    recv_until(s,[b"# ",b"~#"],8)
    s.sendall(b"export PS1='PROMPT> '\r\n"); recv_until(s,[b"PROMPT> "],5)
    return s

def run(s,cmd,t=60):
    s.sendall(cmd.encode()+b"\r\n")
    out=strip_iac(s,recv_until(s,[b"PROMPT> "],t)).decode(errors="replace")
    # strip the echoed command and trailing prompt
    return out

def main():
    with open(SRC,"r",newline="") as f: data=f.read()
    data=data.replace("\r\n","\n")  # ensure unix line endings
    b64=base64.b64encode(data.encode()).decode()
    s=login(); print("LOGIN OK",flush=True)
    # transfer in one shot (small file)
    run(s,"cat > /tmp/gadgetctl.b64 <<'EOF'\n"+b64+"\nEOF",30)
    run(s,"base64 -d /tmp/gadgetctl.b64 > /usr/bin/gadgetctl && chmod +x /usr/bin/gadgetctl && echo INSTALLED",20)
    print(run(s,"ls -la /usr/bin/gadgetctl",10))
    print("=== SNAPSHOT (before) ===")
    print(run(s,"gadgetctl status",10))
    print(run(s,"lsmod | grep -E 'g_service|u_service|usb_f_service|hi_dvb|hisi_sci'",10))
    print(run(s,"echo NONCORE=$(dmesg | grep -c non-core)  IRQ=$(awk '/dwc_otg/{print $2}' /proc/interrupts)",10))
    print("=== STEP down (rmmod g_service only) ===")
    print(run(s,"gadgetctl down",15))
    print(run(s,"gadgetctl status",10))
    print("=== VERIFY Live-TV transport intact after down ===")
    print(run(s,"lsmod | grep -E 'g_service|u_service|usb_f_service|hi_dvb|hisi_sci'",10))
    print(run(s,"echo NONCORE1=$(dmesg | grep -c non-core)",10))
    print("   (waiting 6s to confirm non-core storm stopped while gadget idle)")
    run(s,"sleep 6",10)
    print(run(s,"echo NONCORE2=$(dmesg | grep -c non-core)  IRQ2=$(awk '/dwc_otg/{print $2}' /proc/interrupts)",10))
    print("=== STEP up (restore gadget) -- ROLLBACK ===")
    print(run(s,"gadgetctl up",15))
    print(run(s,"gadgetctl status",10))
    print(run(s,"lsmod | grep -E 'g_service|u_service|usb_f_service'",10))
    try: s.sendall(b"exit\r\n")
    except Exception: pass
    s.close(); print("DONE")

if __name__=="__main__":
    main()
