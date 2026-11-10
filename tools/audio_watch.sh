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

save_evidence() {
    f="$D/event_$(date +%Y%m%d_%H%M%S).txt"
    {
        echo "uptime $(cat "$PROC/uptime")"
        cat "$D/port" 2>/dev/null
        grep -E 'aiao|dmx|dwc_otg' "$PROC/interrupts"
        ( grep -E '^ +0 ' "$PROC/msp/demux_chanbuf" 2>/dev/null & ); sleep 1
        $DMESG | tail -n 40
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
log "start streak=$streak"
if [ "$PANIC_SEC" != 0 ]; then
    old=$(cat "$PROC/sys/kernel/panic" 2>/dev/null)
    echo "$PANIC_SEC" > "$PROC/sys/kernel/panic" 2>/dev/null
    log "kernel.panic $old -> $(cat "$PROC/sys/kernel/panic" 2>/dev/null)"
fi
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
