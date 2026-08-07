#!/bin/sh
# freeze_watch.sh — light on-box watcher. When A/V freeze signature persists,
# write one forensic snapshot via freeze_dump.sh (debounced).
#
# Conf (optional): /data/freeze_tools/freeze_watch.conf
#   INTERVAL_SEC=30
#   HOLD_SEC=60
#   COOLDOWN_SEC=1800

TOOLS="/data/freeze_tools"
DUMP="$TOOLS/freeze_dump.sh"
CONF="$TOOLS/freeze_watch.conf"
STATE="$TOOLS/watch.state"
LAST_SNAP="$TOOLS/last_snap_ts"
LOG="$TOOLS/freeze_watch.log"

INTERVAL_SEC=30
HOLD_SEC=60
COOLDOWN_SEC=1800

if [ -f "$CONF" ]; then
    # shellcheck disable=SC1090
    . "$CONF"
fi

log() {
    echo "$(date 2>/dev/null) $*" >> "$LOG" 2>/dev/null
}

is_av_frozen() {
    # bianbiang must be alive (UI path)
    pidof bianbiang >/dev/null 2>&1 || return 1

    AV="/proc/msp/avplay00"
    [ -e "$AV" ] || return 1

    # Prefer CurStatus:STOP; also Vid disabled + null PID
    if grep -q 'CurStatus[[:space:]]*:STOP' "$AV" 2>/dev/null; then
        return 0
    fi
    if grep -q 'Vid Enable[[:space:]]*:FALSE' "$AV" 2>/dev/null \
        && grep -q 'VidPid[[:space:]]*:0x1fff' "$AV" 2>/dev/null; then
        return 0
    fi
    # EAGAIN / empty read often means wedged play path after soft restart
    if ! head -c 256 "$AV" >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

mkdir -p "$TOOLS" 2>/dev/null
BAD_SINCE=0
log "watch started interval=${INTERVAL_SEC}s hold=${HOLD_SEC}s"

while true; do
    if is_av_frozen; then
        NOW=$(date +%s 2>/dev/null || echo 0)
        if [ "$BAD_SINCE" -eq 0 ] 2>/dev/null; then
            BAD_SINCE=$NOW
            log "freeze signature seen; holding ${HOLD_SEC}s"
        fi
        HELD=$(( NOW - BAD_SINCE ))
        if [ "$HELD" -ge "$HOLD_SEC" ] 2>/dev/null; then
            LAST=0
            [ -f "$LAST_SNAP" ] && LAST=$(cat "$LAST_SNAP" 2>/dev/null || echo 0)
            AGE=$(( NOW - LAST ))
            if [ "$AGE" -ge "$COOLDOWN_SEC" ] 2>/dev/null; then
                if [ -x "$DUMP" ] || [ -f "$DUMP" ]; then
                    log "triggering dump (held=${HELD}s)"
                    OUT=$(sh "$DUMP" watch 2>&1)
                    log "$OUT"
                    echo "$NOW" > "$LAST_SNAP"
                else
                    log "dump script missing: $DUMP"
                fi
            else
                log "cooldown ${AGE}s < ${COOLDOWN_SEC}s; skip dump"
            fi
            # reset hold so we do not spin; cooldown gates next dump
            BAD_SINCE=0
        fi
    else
        BAD_SINCE=0
    fi
    sleep "$INTERVAL_SEC"
done
