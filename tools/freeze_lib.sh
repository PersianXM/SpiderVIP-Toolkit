#!/bin/sh
# freeze_lib.sh — busybox/ash helpers for on-box freeze watch/dump/recovery.
# Source only. Do not execute this file.

TOOLS="${TOOLS:-/data/freeze_tools}"
CONF="${CONF:-$TOOLS/freeze_watch.conf}"
LOG="${LOG:-$TOOLS/freeze_watch.log}"
LIVE_PROG="${LIVE_PROG:-/data/gx/live_prog}"
LIVE_PROG_BAK="${LIVE_PROG_BAK:-/data/live_prog_usals_ok.bak}"
LIVE_PROG_GOOD="${LIVE_PROG_GOOD:-$TOOLS/live_prog.last_good}"
RECOVERY_LOG="${RECOVERY_LOG:-$TOOLS/recovery.log}"
DISABLE_FILE="${DISABLE_FILE:-$TOOLS/DISABLE_AUTO_RECOVERY}"

INTERVAL_SEC=30
HOLD_SEC=120
COOLDOWN_SEC=1800
AUTO_RECOVERY=1
BOOT_GRACE_SEC=180
MAX_RECOVERIES=2
RECOVERY_WINDOW_SEC=86400
MSP_READ_SEC=3
DUMP_MAX_SEC=25

freeze_load_conf() {
    if [ -f "$CONF" ]; then
        # shellcheck disable=SC1090
        . "$CONF"
    fi
}

freeze_log() {
    echo "$(date 2>/dev/null) $*" >> "$LOG" 2>/dev/null
}

freeze_now() {
    date +%s 2>/dev/null || echo 0
}

freeze_uptime_sec() {
    cut -d. -f1 /proc/uptime 2>/dev/null || echo 0
}

# Run a command for at most $1 seconds.
# Do not use busybox `timeout`: it waits on D-state /proc/msp reads and hangs.
# Returns 124 on timeout, including uninterruptible children we refuse to wait on.
freeze_run_timeout() {
    _sec=$1
    shift
    [ "$_sec" -gt 0 ] 2>/dev/null || _sec=3

    "$@" &
    _pid=$!
    _i=0
    while [ "$_i" -lt "$_sec" ]; do
        if ! kill -0 "$_pid" 2>/dev/null; then
            wait "$_pid"
            return $?
        fi
        sleep 1
        _i=$((_i + 1))
    done
    kill "$_pid" 2>/dev/null
    sleep 1
    kill -9 "$_pid" 2>/dev/null
    if kill -0 "$_pid" 2>/dev/null; then
        return 124
    fi
    wait "$_pid" 2>/dev/null
    return 124
}

# Timed copy of a (possibly blocking) /proc node. $1=src $2=dst
freeze_timed_grab() {
    _src=$1
    _dst=$2
    _sec=${MSP_READ_SEC:-3}
    : > "$_dst"
    freeze_run_timeout "$_sec" head -c 131072 "$_src" > "$_dst" 2>&1
    _rc=$?
    if [ "$_rc" -eq 124 ]; then
        echo "grab_timeout:$_src" >> "$_dst"
        return 124
    fi
    if [ "$_rc" -ne 0 ]; then
        echo "grab_fail:$_src rc=$_rc" >> "$_dst"
        return "$_rc"
    fi
    return 0
}

# Sample avplay without hanging freeze_watch. 0 = frozen, 1 = not frozen.
freeze_is_av_frozen() {
    pidof bianbiang >/dev/null 2>&1 || return 1

    _av="/proc/msp/avplay00"
    [ -e "$_av" ] || return 1

    _tmp="$TOOLS/avplay.sample"
    mkdir -p "$TOOLS" 2>/dev/null
    freeze_timed_grab "$_av" "$_tmp"
    _rc=$?
    if [ "$_rc" -eq 124 ]; then
        return 0
    fi
    if grep -qi 'Resource temporarily unavailable' "$_tmp" 2>/dev/null; then
        return 0
    fi
    if grep -q 'CurStatus[[:space:]]*:STOP' "$_tmp" 2>/dev/null; then
        if [ ! -e /proc/msp/vdec00 ]; then
            return 0
        fi
        if grep -q 'VidPid[[:space:]]*:0x1fff' "$_tmp" 2>/dev/null; then
            return 0
        fi
        if grep -q 'Vid Enable[[:space:]]*:FALSE' "$_tmp" 2>/dev/null; then
            return 0
        fi
    fi
    if grep -q 'Vid Enable[[:space:]]*:FALSE' "$_tmp" 2>/dev/null \
        && grep -q 'VidPid[[:space:]]*:0x1fff' "$_tmp" 2>/dev/null; then
        return 0
    fi
    return 1
}

freeze_count_recent_recoveries() {
    _now=$(freeze_now)
    _win=${RECOVERY_WINDOW_SEC:-86400}
    _n=0
    if [ ! -f "$RECOVERY_LOG" ]; then
        echo 0
        return
    fi
    while read _ts _rest; do
        [ -n "$_ts" ] || continue
        _age=$((_now - _ts))
        if [ "$_age" -ge 0 ] 2>/dev/null && [ "$_age" -lt "$_win" ] 2>/dev/null; then
            _n=$((_n + 1))
        fi
    done < "$RECOVERY_LOG"
    echo "$_n"
}

freeze_recovery_allowed() {
    if [ "${AUTO_RECOVERY:-0}" != "1" ]; then
        freeze_log "recovery skipped: AUTO_RECOVERY=${AUTO_RECOVERY:-0}"
        return 1
    fi
    if [ -f "$DISABLE_FILE" ]; then
        freeze_log "recovery skipped: $DISABLE_FILE present"
        return 1
    fi
    _up=$(freeze_uptime_sec)
    if [ "$_up" -lt "${BOOT_GRACE_SEC:-180}" ] 2>/dev/null; then
        freeze_log "recovery skipped: uptime ${_up}s < BOOT_GRACE_SEC=${BOOT_GRACE_SEC}"
        return 1
    fi
    _n=$(freeze_count_recent_recoveries)
    if [ "$_n" -ge "${MAX_RECOVERIES:-2}" ] 2>/dev/null; then
        freeze_log "recovery skipped: $_n recoveries in window (max ${MAX_RECOVERIES})"
        return 1
    fi
    return 0
}

freeze_backup_live_prog() {
    if [ ! -s "$LIVE_PROG" ]; then
        freeze_log "live_prog missing or empty; skip backup"
        return 1
    fi
    cp "$LIVE_PROG" "$LIVE_PROG_BAK" 2>/dev/null
    cp "$LIVE_PROG" "$LIVE_PROG_GOOD" 2>/dev/null
    sync
    freeze_log "live_prog backed up to $LIVE_PROG_BAK"
    return 0
}

freeze_refresh_last_good() {
    [ -s "$LIVE_PROG" ] || return 1
    _now=$(freeze_now)
    _last=0
    [ -f "$TOOLS/last_good_ts" ] && _last=$(cat "$TOOLS/last_good_ts" 2>/dev/null || echo 0)
    _age=$((_now - _last))
    if [ "$_age" -lt 3600 ] 2>/dev/null; then
        return 0
    fi
    cp "$LIVE_PROG" "$LIVE_PROG_GOOD" 2>/dev/null
    echo "$_now" > "$TOOLS/last_good_ts" 2>/dev/null
    return 0
}
