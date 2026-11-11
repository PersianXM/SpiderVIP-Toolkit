#!/bin/sh
# audio_watch.sh - on-box auto recovery for the audio-output freeze.
#
# The freeze seen on 2026-11-02 and 2026-11-09: the AO driver lock stays
# taken, audio DMA stops, the demux audio channel fills, and the demux then
# stops reading the TS input. Only a reboot clears it. This script reboots
# the box only when all three signs agree:
#   1. the aiao (audio DMA) interrupt count has not moved for STALL_SEC
#   2. the kernel log shows "call HI_DVB_DMX_GetTSBuffer failed"
#   3. demux RAM port 128 is at least PORT_FULL_PCT percent full
# Menus, channel changes and standby stop audio DMA but never fill the
# port, so they do not trigger it.
#
# Safety: no action in the first MIN_UPTIME seconds after boot. After
# MAX_STREAK auto reboots in a row it only logs, so a box that freezes
# right after every boot cannot loop forever. "In a row" means each boot
# started from this script's own reboot: a normal power-off or reboot in
# between, or RESET_UPTIME of healthy running, starts the count again.
# touch $D/disable to turn it off. It never changes drivers, settings or
# g_service.
#
# It also sets kernel.panic to PANIC_SEC. The vendor kernel panics on a soft
# lockup or a 120 s hung task but has kernel.panic=0, so a panic leaves the
# box frozen with no picture, network or remote until the power is cut.
# With PANIC_SEC the kernel reboots by itself that many seconds after a
# panic. The value is not saved: every boot starts at 0 until this script
# runs again. AW_PANIC_SEC=0 leaves it alone.
#
# It also keeps the kernel log in $D/kmsg. dmesg holds only about 5 s on
# this box, because the USB gadget prints about 13 lines a second, so a
# kernel fault at the start of a freeze is gone before anyone looks. In
# both audio freezes one player thread was missing from the process, which
# fits a thread killed by a kernel fault while it held the AO lock; the
# saved log is there to show that fault. AW_KMSG_KEEP=0 turns it off.
#
# Kernel Oops: the freeze of 2026-11-10 began with an Oops in an AO ioctl
# (AO_Track_GetDelayMs). The thread died holding the AO lock and the three
# signs above only agreed 74 s later. An Oops sets bit 128 in
# kernel.tainted, so when that bit appears while this script runs it saves
# the evidence and reboots at once, without waiting for the three signs and
# without the MIN_UPTIME wait. The MAX_STREAK limit still applies. An Oops
# from before this script started is only logged. AW_OOPS_REBOOT=0 turns
# the reboot off; the Oops is then only logged.

D=${AW_DIR:-/data/audio_watch}
PROC=${AW_PROC:-/proc}
INTERVAL=${AW_INTERVAL:-10}
STALL_SEC=${AW_STALL_SEC:-60}
MIN_UPTIME=${AW_MIN_UPTIME:-600}
RESET_UPTIME=${AW_RESET_UPTIME:-1800}
MAX_STREAK=${AW_MAX_STREAK:-3}
PORT_FULL_PCT=${AW_PORT_FULL_PCT:-90}
REBOOT=${AW_REBOOT:-reboot_box}
DMESG=${AW_DMESG:-dmesg}
PANIC_SEC=${AW_PANIC_SEC:-10}
KMSG=${AW_KMSG:-/dev/kmsg}
KMSG_KEEP=${AW_KMSG_KEEP:-3000}
OOPS_REBOOT=${AW_OOPS_REBOOT:-1}
OOPS_WAIT=${AW_OOPS_WAIT:-3}

# Keep running after the Telnet session that started it closes.
trap '' HUP

mkdir -p "$D"
[ -e "$D/disable" ] && exit 0
# One copy per boot. The boot id keeps a stale pid from the last boot,
# now reused by another process, from looking like a running copy.
boot=$(cat "$PROC/sys/kernel/random/boot_id" 2>/dev/null)
if [ -e "$D/pid" ]; then
    set -- $(cat "$D/pid")
    if [ "$2" = "$boot" ] && kill -0 "$1" 2>/dev/null; then
        exit 0
    fi
fi
echo "$$ $boot" > "$D/pid"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') up=$(cut -d' ' -f1 "$PROC/uptime") $*" >> "$D/log"
    if [ "$(wc -c < "$D/log")" -gt 65536 ]; then
        tail -n 200 "$D/log" > "$D/log.tmp" && mv "$D/log.tmp" "$D/log"
    fi
}

reboot_box() {
    touch "$D/pending"
    sync
    /sbin/reboot -f
    sleep 60
    echo b > "$PROC/sysrq-trigger"
}

uptime_s() {
    cut -d. -f1 "$PROC/uptime"
}

# 128 once the kernel has had an Oops since boot (the D taint bit), else 0.
oops_bit() {
    t=$(cat "$PROC/sys/kernel/tainted" 2>/dev/null)
    echo $(( ${t:-0} & 128 ))
}

aiao_count() {
    awk '/aiao/ { print $2 + $3 + $4 + $5 }' "$PROC/interrupts"
}

# /proc/msp reads can block forever on a wedged player, so read in the
# background and use whatever arrived after 2 s.
port_used_pct() {
    rm -f "$D/port"
    ( grep -E '^ *128 ' "$PROC/msp/demux_port" > "$D/port" 2>/dev/null & )
    sleep 2
    sed -n 's/.*(\([0-9]*\)%).*/\1/p' "$D/port" 2>/dev/null | head -n 1
}

# Every kernel line except the gadget noise goes to $D/kmsg, written line
# by line so nothing is lost when the box reboots. The last KMSG_KEEP lines
# stay there and the ones before them in kmsg.old. /dev/kmsg gives each
# reader its own position, so klogd and dmesg lose nothing. The tap stops by
# itself once $D/tap no longer holds this copy's pid (reinstall or remove).
klog_tap() {
    echo "$$" > "$D/tap"
    (
        trap '' HUP
        while [ "$(cat "$D/tap" 2>/dev/null)" = "$$" ]; do
            cat "$KMSG" 2>/dev/null | awk -v f="$D/kmsg" -v t="$D/tap" -v me="$$" \
                -v keep="$KMSG_KEEP" -v n="$(cat "$D/kmsg" 2>/dev/null | wc -l)" '
                NR % 200 == 0 { cur = ""; getline cur < t; close(t); if (cur != me) exit }
                /service gadget|gservice_ts_thread/ { next }
                {
                    print >> f; close(f)
                    if (++n >= keep) { system("mv \"" f "\" \"" f ".old\""); n = 0 }
                }'
            sleep 5
        done
    ) </dev/null >/dev/null 2>&1 &
}

save_evidence() {
    f="$D/event_$(date +%Y%m%d_%H%M%S).txt"
    {
        echo "uptime $(cat "$PROC/uptime")"
        cat "$D/port" 2>/dev/null
        grep -E 'aiao|dmx|dwc_otg' "$PROC/interrupts"
        ( grep -E '^ +0 ' "$PROC/msp/demux_chanbuf" 2>/dev/null & ); sleep 1
        $DMESG | tail -n 40
        # A kernel fault sets the D bit (128) in tainted. A healthy player
        # has four playback threads; both freezes so far had three.
        echo "tainted $(cat "$PROC/sys/kernel/tainted" 2>/dev/null)"
        P=$(pidof bianbiang 2>/dev/null)
        if [ -n "$P" ]; then
            echo "bianbiang=$P $(grep Threads "$PROC/$P/status" 2>/dev/null)"
            for t in "$PROC/$P"/task/*; do
                echo "T ${t##*/} $(cat "$t/wchan" 2>/dev/null) $(cat "$t/syscall" 2>/dev/null)"
            done
        fi
        ( cat "$PROC/msp/*adsp" 2>/dev/null & ); sleep 1
        # sound0 uses the same SND_0 card pointer that was bad in the Oops
        # of 2026-11-10, and takes no AO lock. A normal printout means the
        # pointer in memory is good again; no printout and a second Oops in
        # the kmsg below means it stayed bad. That Oops only kills this cat.
        echo "--- sound0"
        ( ( cat "$PROC/msp/sound0"; echo "sound0 exit=$?" ) 2>&1 & ); sleep 2
        echo "--- kmsg"
        cat "$D/kmsg.old" "$D/kmsg" 2>/dev/null | tail -n 400
    } > "$f" 2>&1
    ls -t "$D"/event_*.txt 2>/dev/null | sed -n '6,$p' | while read -r old; do rm -f "$old"; done
}

# The pending mark is left only by our own reboot. Without it the last
# boot ended normally, so earlier auto reboots no longer count as in a row.
if [ -e "$D/pending" ]; then
    rm -f "$D/pending"
    streak=$(cat "$D/streak" 2>/dev/null)
    streak=${streak:-0}
else
    streak=0
    echo 0 > "$D/streak"
fi
# The clock is not set yet this early in a boot, so every boot logs the same
# date here. The boot id tells one boot from the next.
log "start streak=$streak boot=${boot%%-*}"
if [ "$PANIC_SEC" != 0 ]; then
    old=$(cat "$PROC/sys/kernel/panic" 2>/dev/null)
    echo "$PANIC_SEC" > "$PROC/sys/kernel/panic" 2>/dev/null
    log "kernel.panic $old -> $(cat "$PROC/sys/kernel/panic" 2>/dev/null)"
fi
if [ "$KMSG_KEEP" != 0 ] && [ -e "$KMSG" ]; then
    klog_tap
    log "kernel log tap on"
fi
oops=$(oops_bit)
[ "$oops" = 0 ] || log "kernel Oops already in tainted at start, not acting on it"
prev=""
stalled=0
held=0
healthy_logged=0
while :; do
    sleep "$INTERVAL"
    up=$(uptime_s)
    if [ "$healthy_logged" = 0 ] && [ "$up" -ge "$RESET_UPTIME" ] && [ "$streak" != 0 ]; then
        streak=0
        echo 0 > "$D/streak"
        healthy_logged=1
        log "healthy run, streak reset"
    fi
    if [ "$oops" = 0 ] && [ "$(oops_bit)" != 0 ]; then
        oops=128
        tainted=$(cat "$PROC/sys/kernel/tainted" 2>/dev/null)
        if [ "$OOPS_REBOOT" = 0 ]; then
            log "kernel Oops (tainted=$tainted), reboot on Oops is off"
        elif [ "$streak" -ge "$MAX_STREAK" ]; then
            log "kernel Oops (tainted=$tainted) but $streak auto reboots in a row, not rebooting"
        else
            streak=$((streak + 1))
            echo "$streak" > "$D/streak"
            # Give the tap time to store the whole Oops text.
            sleep "$OOPS_WAIT"
            save_evidence
            log "kernel Oops (tainted=$tainted), rebooting, streak=$streak"
            $REBOOT
            exit 0
        fi
    fi
    ai=$(aiao_count)
    if [ -n "$ai" ] && [ "$ai" = "$prev" ]; then
        stalled=$((stalled + INTERVAL))
    else
        stalled=0
        held=0
    fi
    prev=$ai
    [ "$stalled" -ge "$STALL_SEC" ] || continue
    [ "$held" = 0 ] || continue
    [ "$up" -ge "$MIN_UPTIME" ] || continue
    $DMESG | grep -q 'GetTSBuffer failed' || continue
    pct=$(port_used_pct)
    [ "${pct:-0}" -ge "$PORT_FULL_PCT" ] || continue
    if [ "$streak" -ge "$MAX_STREAK" ]; then
        log "freeze confirmed (aiao=$ai port=$pct%) but $streak auto reboots in a row, not rebooting"
        held=1
        continue
    fi
    streak=$((streak + 1))
    echo "$streak" > "$D/streak"
    save_evidence
    log "freeze confirmed (aiao=$ai stalled=${stalled}s port=$pct%), rebooting, streak=$streak"
    $REBOOT
    exit 0
done
