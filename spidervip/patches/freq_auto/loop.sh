#!/bin/sh
# SpiderVIP automatic frequency update — on-box scheduler.
#
# Started at every boot from /home/gx/local/user_script.
#  * If an apply is waiting for verification (pending.json), verify it first,
#    after the box has settled (runner.py verify may roll back once).
#  * Waits until NTP has set the clock (the box reads 2026-08-14 early in each
#    boot; min_epoch is written at install).
#  * When interval_s (default 7 days) has passed since the last successful run,
#    runs runner.py in the mode from the "mode" file (apply|report). "apply"
#    only starts inside the night window (WINDOW_START..WINDOW_END hours,
#    default 00..06); "report" runs any time. A failed run is retried after
#    RETRY seconds. Runs at the lowest CPU priority.
#
# Files in $D: mode, interval_s, min_epoch, last_run, last_try, pid
# ("<pid> <boot_id>"), disable, pending.json, last_report.json, log.

D=${FA_DIR:-/data/spidervip_freq_auto}
PROC=${FA_PROC:-/proc}
CHECK=${FA_CHECK:-600}
RETRY=${FA_RETRY:-21600}
SETTLE=${FA_SETTLE:-90}
WINDOW_START=${FA_WINDOW_START:-0}
WINDOW_END=${FA_WINDOW_END:-6}
PY=${FA_PY:-python3}

trap '' HUP
cd "$D" || exit 1
echo "$$ $(cat "$PROC/sys/kernel/random/boot_id" 2>/dev/null)" > "$D/pid"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') up=$(cut -d' ' -f1 "$PROC/uptime" 2>/dev/null) $*" >> "$D/log"
    if [ "$(wc -c < "$D/log")" -gt 65536 ]; then
        tail -n 300 "$D/log" > "$D/log.tmp" && mv "$D/log.tmp" "$D/log"
    fi
}

num() { v=$(cat "$1" 2>/dev/null); case "$v" in ''|*[!0-9]*) echo "$2" ;; *) echo "$v" ;; esac; }
mode() { m=$(cat "$D/mode" 2>/dev/null); [ "$m" = apply ] && echo apply || echo report; }
in_window() {
    h=$(date +%H); h=${h#0}; h=${h:-0}
    [ "$h" -ge "$WINDOW_START" ] && [ "$h" -lt "$WINDOW_END" ]
}

log "start mode=$(mode) interval=$(num "$D/interval_s" 604800)s window=${WINDOW_START}-${WINDOW_END}h"

if [ -e "$D/pending.json" ]; then
    log "pending apply: verifying in ${SETTLE}s"
    sleep "$SETTLE"
    nice -n 19 $PY "$D/runner.py" verify >> "$D/log" 2>&1
    log "verify end rc=$?"
fi

waited=0
while :; do
    [ -e "$D/disable" ] && { log "disabled, exit"; exit 0; }
    now=$(date +%s)
    if [ "$now" -lt "$(num "$D/min_epoch" 0)" ]; then
        [ "$waited" = 1 ] || log "waiting for the clock (NTP)"
        waited=1
    elif [ ! -e "$D/pending.json" ]; then
        interval=$(num "$D/interval_s" 604800)
        last=$(num "$D/last_run" 0)
        try=$(num "$D/last_try" 0)
        m=$(mode)
        if [ $((now - last)) -ge "$interval" ] && [ $((now - try)) -ge "$RETRY" ]; then
            if [ "$m" = report ] || in_window; then
                echo "$now" > "$D/last_try"
                log "run $m"
                # An apply that reaches the box writes last_run itself just before
                # its forced reboot; one that fails earlier is retried after RETRY.
                nice -n 19 $PY "$D/runner.py" "$m" >> "$D/log" 2>&1
                rc=$?
                [ "$rc" = 0 ] && echo "$now" > "$D/last_run"
                log "run end rc=$rc"
            fi
        fi
    fi
    sleep "$CHECK"
done
