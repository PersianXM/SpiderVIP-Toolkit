#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blackbox_record.py - long read-only recorder for the A/V freeze hunt.

Keeps one Telnet session open from the PC and streams a sampling loop to
build/blackbox/. It exists because the kernel ring buffer holds only seconds
of history, so the event that starts a freeze hours into a run is otherwise
lost. Nothing survives on the box: the loop lives in tmpfs and ends with the
session. It installs nothing, restarts nothing and changes no setting.

Log line prefixes:
  K  every 3s: USB request count, TS read count, ring buffer time span,
     audio DMA interrupt total (ai)
  E  any kernel message that is not the routine USB/TS noise
  S  every 30s: load and free memory
  I  interrupt totals          P  process state
  A  avplay00 fields           R  demux RAM port 128 line
  M  /proc/msp/stat events     T  chip temperature
  O  audio output DMA count and audio decoder feed
  H  HDMI hotplug event counts  B  demux channel buffers
  W  a /proc/msp read is still blocked from the previous sample
  PC events seen by this recorder (connect, silence, disconnect)

Usage:  python tools/blackbox_record.py [--host IP ...]
Stop with Ctrl+C.
"""
import argparse
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telnet_run

DEFAULT_HOSTS = ["192.168.100.102", "192.168.100.146"]
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "blackbox")
SILENCE_WARN_SEC = 30
SILENCE_RECONNECT_SEC = 120
RETRY_SEC = 30
AUDIO_STALL_SAMPLES = 20  # about 60 s of frozen audio DMA count; channel changes pause it for ~20 s

BOX_LOOP = r"""
D=/var/volatile/bb
mkdir -p $D
rm -f $D/busy
last=0
n=0
while :; do
  now=$(date +%s)
  dmesg > $D/k 2>/dev/null
  sed -n 's/^\[ *\([0-9.]*\)\].*/\1/p' $D/k > $D/t
  a=$(head -n 1 $D/t)
  z=$(tail -n 1 $D/t)
  echo "K $now up=$(cut -d' ' -f1 /proc/uptime) rq=$(grep -c 'req23\.03' $D/k) ts=$(grep -c gservice_ts_thread $D/k) ring=$a..$z ai=$(awk '/aiao/{print $2+$3+$4+$5}' /proc/interrupts)"
  awk -v l="$last" '/^\[/ { t=$0; sub(/^\[ */,"",t); sub(/\].*/,"",t); if (t+0>l+0 && $0 !~ /req23\.03|gservice_ts_thread/) print "E " $0 }' $D/k
  [ -n "$z" ] && last=$z
  if [ $((n%10)) -eq 0 ]; then
    echo "S $now $(cat /proc/loadavg) $(grep MemAvailable /proc/meminfo)"
    grep -E 'dwc_otg|ir_std| dmx| tde|vdec_vdh|aiao' /proc/interrupts | awk '{print "I",$1,$2+$3+$4+$5,$NF}'
    ps axo stat,wchan:24,rss,comm | grep -E 'bianbiang$|kgservice|streamrelay' | sed 's/^/P /'
    if [ -e $D/busy ]; then
      echo "W msp read still blocked"
    else
      ( : > $D/busy
        grep -E 'Stream Type|CurStatus|Vid Enable|VidPid|Aud Enable|AcquireFrame' /proc/msp/avplay00 > $D/a 2>&1
        grep -E '^ *128 ' /proc/msp/demux_port > $D/b 2>&1
        grep -E 'CONNECT|LOCKED|CWSET|STREAMIN|FRAMEDECED|VOGET|TOTAL' /proc/msp/stat > $D/c 2>&1
        grep Temperature /proc/msp/chip_temp > $D/e 2>&1
        { grep -m1 DmaCnt /proc/msp/sound0; grep -m1 SendCnt /proc/msp/sound0; grep ReceiveFrame /proc/msp/adec00; } > $D/o 2>&1
        grep '^WR:' /proc/msp/hdmi0 > $D/h 2>&1
        grep -E '^ +0 +[0-9]+ +[0-9]+ +[0-9]+ ' /proc/msp/demux_chanbuf > $D/g 2>&1
        rm -f $D/busy ) &
      sleep 1
      sed 's/^/A /' $D/a 2>/dev/null
      sed 's/^/R /' $D/b 2>/dev/null
      sed 's/^/M /' $D/c 2>/dev/null
      sed 's/^/T /' $D/e 2>/dev/null
      sed 's/^/O /' $D/o 2>/dev/null
      sed 's/^/H /' $D/h 2>/dev/null
      sed 's/^/B /' $D/g 2>/dev/null
    fi
  fi
  n=$((n+1))
  sleep 3
done
""".strip()


class AudioWatch:
    """Flags the two signs that marked the 2026-11-02 freeze.

    The audio DMA count also stops in menus and between channels, when avplay
    reports STOP, so that alone is only raised while the last status was PLAY
    or could not be read. GetTSBuffer failures mean the demux input is full.
    """

    def __init__(self):
        self.last = None
        self.same = 0
        self.alerted = False
        self.status = "PLAY"
        self.tsbuf_alerted = False

    def check(self, text, log):
        if text.startswith("A CurStatus"):
            self.status = text.split(":", 1)[1].split()[0] if ":" in text else "PLAY"
            return
        if text.startswith("E ") and "GetTSBuffer failed" in text:
            if not self.tsbuf_alerted:
                self.tsbuf_alerted = True
                log.write("PC ALERT demux input full (GetTSBuffer failed) - freeze")
            return
        if not text.startswith("K ") or " ai=" not in text:
            return
        value = text.rsplit(" ai=", 1)[1].strip()
        if not value.isdigit():
            return
        self.same = self.same + 1 if value == self.last else 0
        self.last = value
        if self.same >= AUDIO_STALL_SAMPLES and not self.alerted and self.status != "STOP":
            self.alerted = True
            log.write("PC ALERT audio DMA stopped while playing (aiao=%s) - likely freeze start" % value)
        elif self.same == 0 and (self.alerted or self.tsbuf_alerted):
            self.alerted = False
            self.tsbuf_alerted = False
            log.write("PC audio DMA moving again (aiao=%s)" % value)


class Log:
    def __init__(self, path):
        self.handle = open(path, "a", encoding="utf-8")
        self.last_beat = 0.0

    def write(self, text):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.handle.write("%s | %s\n" % (stamp, text))
        self.handle.flush()
        now = time.time()
        if text.startswith(("E ", "W ", "PC ")):
            print("%s | %s" % (stamp, text), flush=True)
        elif now - self.last_beat >= 60:
            self.last_beat = now
            print("%s | recording ... %s" % (stamp, text[:70]), flush=True)


def start_loop(sock):
    body = b"cat > /var/volatile/bb.sh <<'BBEOF'\r\n"
    body += BOX_LOOP.replace("\n", "\r\n").encode()
    body += b"\r\nBBEOF\r\n"
    sock.sendall(body)
    telnet_run.recv_until(sock, [b"PROMPT> "], 8)
    sock.sendall(b"stty -echo; sh /var/volatile/bb.sh\r\n")


def stream(sock, log):
    """Copy box output into the log until the session ends or goes quiet."""
    sock.settimeout(5)
    watch = AudioWatch()
    pending = b""
    last_data = time.time()
    warned = False
    while True:
        try:
            data = sock.recv(8192)
        except socket.timeout:
            quiet = time.time() - last_data
            if quiet >= SILENCE_WARN_SEC and not warned:
                warned = True
                log.write("PC box silent for %ds" % quiet)
            if quiet >= SILENCE_RECONNECT_SEC:
                return "silent for %ds" % quiet
            continue
        if not data:
            return "session closed"
        if warned:
            log.write("PC box output resumed after %ds" % (time.time() - last_data))
            warned = False
        last_data = time.time()
        pending += telnet_run.strip_iac(sock, data)
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            text = line.decode(errors="replace").strip("\r\n ")
            if text:
                log.write(text)
                watch.check(text, log)


def connect(hosts, log):
    for host in hosts:
        telnet_run.HOST = host
        try:
            sock = telnet_run.login()
        except (OSError, RuntimeError) as exc:
            log.write("PC cannot reach %s: %s" % (host, exc))
            continue
        log.write("PC connected to %s" % host)
        return sock
    return None


def main():
    parser = argparse.ArgumentParser(description="Read-only freeze recorder")
    parser.add_argument("--host", action="append", help="receiver IP; repeat to try several")
    args = parser.parse_args()
    hosts = args.host or DEFAULT_HOSTS

    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.abspath(os.path.join(LOG_DIR, "blackbox_%s.log" % time.strftime("%Y%m%d_%H%M%S")))
    log = Log(path)
    print("log file: %s" % path, flush=True)
    print("Keep this window open. Stop with Ctrl+C.", flush=True)

    try:
        while True:
            sock = connect(hosts, log)
            if sock is None:
                time.sleep(RETRY_SEC)
                continue
            try:
                start_loop(sock)
                reason = stream(sock, log)
            except OSError as exc:
                reason = str(exc)
            finally:
                try:
                    sock.close()
                except OSError:
                    pass
            log.write("PC session ended: %s" % reason)
            time.sleep(RETRY_SEC)
    except KeyboardInterrupt:
        print("\nstopped. log file: %s" % path, flush=True)


if __name__ == "__main__":
    main()
