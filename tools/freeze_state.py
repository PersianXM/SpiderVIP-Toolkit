#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
freeze_state.py - one read-only picture of the receiver while it is frozen.

Run it while the box is still frozen, before any reboot or channel change.
It reads process, thread, interrupt, player, demux and kernel log state, twice
where a counter matters, so we can see what still moves and what has stopped.
It writes only small temp files under /var/volatile/fs and changes nothing.
Every /proc/msp read runs in the background with a 2 s wait, because a wedged
player node can block a reader forever.

Usage:  python tools/freeze_state.py [--host IP]
Output: build/freeze_state/freeze_state_<time>.txt
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telnet_run

DEFAULT_HOSTS = ["192.168.100.102", "192.168.100.146"]
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "freeze_state")
DEMUX_NODES = ("demux_main demux_chan demux_chanbuf demux_filter demux_pcr demux_rec "
               "demux_rec_index demux_key vpss01 win0100 vdec_ctrl low_delay_statistics log")
MSP_NODES = ("avplay00 avplay01 sync00 sync01 vdec00 vdec01 adec00 adec01 "
             "demux_port stat chip_temp vo win hdmi0 hdmi0_ao sound0 adsp disp0 disp1")

COMMANDS = [
    "D=/var/volatile/fs; mkdir -p $D; "
    "ev() { f=$D/$(echo $1 | tr / _).$2; ( cat \"/proc/msp/$1\" > $f 2>&1 & ); sleep 2; "
    "echo \"--- $1 ($2)\"; head -c 16000 $f; echo; }",
    "date; cat /proc/uptime /proc/loadavg",
    "P=$(pidof bianbiang); echo bianbiang=$P; grep -E 'VmRSS|VmSize|Threads' /proc/$P/status",
    "ps axo pid,stat,wchan:24,etime,rss,comm",
    "th() { for t in /proc/$P/task/*; do echo \"$(basename $t) $(cat $t/comm) "
    "$(cat $t/wchan) $(sed 's/.*) //' $t/stat | cut -d' ' -f1,12,13)\"; done; }; "
    "th > $D/th1; sleep 5; th > $D/th2; echo 'tid comm wchan state utime stime'; "
    "cat $D/th1; echo '--- 5 s later'; cat $D/th2",
    "grep -vE '^ +[0-9]+: +0 +0 +0 +0 ' /proc/interrupts > $D/i1; sleep 5; "
    "grep -vE '^ +[0-9]+: +0 +0 +0 +0 ' /proc/interrupts > $D/i2; "
    "cut -c1-200 $D/i1; echo '--- 5 s later'; cut -c1-200 $D/i2",
    "ls /proc/msp",
    "for n in %s; do [ -e /proc/msp/$n ] && ev $n 1; done" % MSP_NODES,
    "sleep 3; for n in avplay00 avplay01 demux_port stat; do [ -e /proc/msp/$n ] && ev $n 2; done",
    "for n in %s; do [ -e /proc/msp/$n ] && ev $n 1; done" % DEMUX_NODES,
    "ls -la /proc/msp/pvr_$P 2>&1; for f in /proc/msp/pvr_$P/*; do [ -f $f ] && ev ${f#/proc/msp/} 1; done",
    "for t in 1497 1498 652 1177 $(ls /proc/$P/task); do w=$(cat /proc/$t/wchan 2>/dev/null); "
    "case \"$w\" in hrtimer_nanosleep|poll_schedule_timeout|inet_csk_accept|pipe_wait) continue;; esac; "
    "echo \"--- stack $t $(cat /proc/$t/comm 2>/dev/null) $w\"; cat /proc/$t/stack 2>&1 | head -n 25; done",
    "for t in $(ls /proc/$P/task); do w=$(cat /proc/$P/task/$t/wchan 2>/dev/null); "
    "case \"$w\" in down_*|*mutex*|*Wait*|*wait_event*) ;; *) continue;; esac; "
    "sc=$(cat /proc/$P/task/$t/syscall 2>&1); set -- $sc; "
    "echo \"--- syscall $t $w: $sc\"; ls -l /proc/$P/fd/$(($2)) 2>&1 | sed 's/.*-> /fd target: /'; done",
    "echo 'all threads: tid wchan syscall'; for t in $(ls /proc/$P/task); do "
    "echo \"$t $(cat /proc/$P/task/$t/wchan 2>/dev/null) $(cut -d' ' -f1-4 /proc/$P/task/$t/syscall 2>&1)\"; done",
    "dmesg | wc -l; dmesg | cut -c1-170",
    "grep -E 'MemTotal|MemFree|MemAvailable|Cached|Swap' /proc/meminfo",
    "ls -la /var/log; tail -n 200 /var/log/messages 2>&1 | cut -c1-200",
    "ls /proc/$P/fd | wc -l; ls -l /proc/$P/fd 2>/dev/null | grep -v socket | awk '{print \"fd\", $(NF-2), $NF}'",
    "date; cat /proc/uptime",
]


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def main():
    parser = argparse.ArgumentParser(description="Read-only snapshot of a frozen receiver")
    parser.add_argument("--host", action="append", help="receiver IP; repeat to try several")
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.abspath(os.path.join(OUT_DIR, "freeze_state_%s.txt" % time.strftime("%Y%m%d_%H%M%S")))
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with open(path, "w", encoding="utf-8") as output:
        sys.stdout = Tee(sys.__stdout__, output)
        try:
            sock = None
            for host in args.host or DEFAULT_HOSTS:
                telnet_run.HOST = host
                try:
                    sock = telnet_run.login()
                    print("connected to %s at %s\n" % (host, time.strftime("%Y-%m-%d %H:%M:%S")), flush=True)
                    break
                except (OSError, RuntimeError) as exc:
                    print("cannot reach %s: %s" % (host, exc), flush=True)
            if sock is None:
                return 1
            for index, command in enumerate(COMMANDS):
                print("==== [%d] %s" % (index, command), flush=True)
                print(telnet_run.run(sock, command, index, timeout=120), flush=True)
                print("", flush=True)
            sock.sendall(b"exit\r\n")
            sock.close()
            print("==== DONE ====", flush=True)
        finally:
            sys.stdout = sys.__stdout__
    print("saved: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
