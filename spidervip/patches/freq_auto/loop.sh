#!/bin/sh
# SpiderVIP automatic frequency update — on-box scheduler (phase 1: report only).
#
# Started at every boot from /home/gx/local/user_script. Waits until NTP has set
# the clock (the box reads 2026-08-14 early in each boot), then runs runner.py
# once the interval has passed since the last successful run. A failed run is
# retried after RETRY seconds. Runs at the lowest CPU priority. Nothing on the
# receiver is changed in this phase; results go to last_report.json and log.
#
# Files in $D: interval_s (seconds between runs), min_epoch (clock sanity floor,
# written at install), last_run, last_try, pid ("<pid> <boot_id>"), disable.

D=${FA_DIR:-/data/spidervip_freq_auto}
PROC=${FA_PROC:-/proc}
CHECK=${FA_CHECK:-600}
RETRY=${FA_RETRY:-21600}
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

log "start (report-only) interval=$(num "$D/interval_s" 6220800)s"
waited=0
while :; do
    [ -e "$D/disable" ] && { log "disabled, exit"; exit 0; }
    now=$(date +%s)
    if [ "$now" -lt "$(num "$D/min_epoch" 0)" ]; then
        [ "$waited" = 1 ] || log "waiting for the clock (NTP)"
        waited=1
    else
        interval=$(num "$D/interval_s" 6220800)
        last=$(num "$D/last_run" 0)
        try=$(num "$D/last_try" 0)
        if [ $((now - last)) -ge "$interval" ] && [ $((now - try)) -ge "$RETRY" ]; then
            echo "$now" > "$D/last_try"
            log "run"
            nice -n 19 $PY "$D/runner.py" >> "$D/log" 2>&1
            rc=$?
            [ "$rc" = 0 ] && echo "$now" > "$D/last_run"
            log "run end rc=$rc"
        fi
    fi
    sleep "$CHECK"
done
