#!/bin/sh
# freeze_watch.sh — light on-box watcher.
# When the A/V freeze signature persists for HOLD_SEC:
#   1. write a time-bounded forensic snapshot
#   2. if AUTO_RECOVERY=1, backup live_prog and /sbin/reboot -f
#
# Conf: /data/freeze_tools/freeze_watch.conf

TOOLS="/data/freeze_tools"
if [ ! -f "$TOOLS/freeze_lib.sh" ]; then
    echo "freeze_lib.sh missing" >&2
    exit 1
fi
# shellcheck disable=SC1091
. "$TOOLS/freeze_lib.sh"
freeze_load_conf

DUMP="$TOOLS/freeze_dump.sh"
RECOVERY="$TOOLS/av_recovery.sh"
STATE="$TOOLS/watch.state"
LAST_SNAP="$TOOLS/last_snap_ts"

mkdir -p "$TOOLS" 2>/dev/null
BAD_SINCE=0
freeze_log "watch started interval=${INTERVAL_SEC}s hold=${HOLD_SEC}s auto=${AUTO_RECOVERY} grace=${BOOT_GRACE_SEC}s max=${MAX_RECOVERIES}"

run_dump_bounded() {
    if [ ! -f "$DUMP" ]; then
        freeze_log "dump script missing: $DUMP"
        return 1
    fi
    freeze_log "triggering dump (held=${1}s)"
    sh "$DUMP" watch >> "$LOG" 2>&1 &
    _dpid=$!
    _max=$((DUMP_MAX_SEC + 10))
    _i=0
    while [ "$_i" -lt "$_max" ]; do
        if ! kill -0 "$_dpid" 2>/dev/null; then
            wait "$_dpid" 2>/dev/null
            echo "$(freeze_now)" > "$LAST_SNAP"
            return 0
        fi
        sleep 1
        _i=$((_i + 1))
    done
    freeze_log "dump still running after ${_max}s; not waiting (possible D-state)"
    echo "$(freeze_now)" > "$LAST_SNAP"
    return 0
}

while true; do
    if freeze_is_av_frozen; then
        NOW=$(freeze_now)
        if [ "$BAD_SINCE" -eq 0 ] 2>/dev/null; then
            BAD_SINCE=$NOW
            freeze_log "freeze signature seen; holding ${HOLD_SEC}s"
        fi
        HELD=$((NOW - BAD_SINCE))
        if [ "$HELD" -ge "$HOLD_SEC" ] 2>/dev/null; then
            LAST=0
            [ -f "$LAST_SNAP" ] && LAST=$(cat "$LAST_SNAP" 2>/dev/null || echo 0)
            AGE=$((NOW - LAST))

            if freeze_recovery_allowed; then
                run_dump_bounded "$HELD"
                freeze_log "calling av_recovery.sh"
                sh "$RECOVERY"
                # reboot -f should not return; if it does, cool down
                BAD_SINCE=0
                sleep "$INTERVAL_SEC"
                continue
            fi

            if [ "$AGE" -ge "$COOLDOWN_SEC" ] 2>/dev/null; then
                run_dump_bounded "$HELD"
            else
                freeze_log "cooldown ${AGE}s < ${COOLDOWN_SEC}s; skip dump"
            fi
            BAD_SINCE=0
        fi
    else
        if [ "$BAD_SINCE" -ne 0 ] 2>/dev/null; then
            freeze_log "freeze signature cleared"
        fi
        BAD_SINCE=0
        _up=$(freeze_uptime_sec)
        if [ "$_up" -ge "$BOOT_GRACE_SEC" ] 2>/dev/null; then
            freeze_refresh_last_good
        fi
    fi
    sleep "$INTERVAL_SEC"
done
