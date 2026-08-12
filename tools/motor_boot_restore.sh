#!/bin/sh
# motor_boot_restore.sh — restore live_prog only if the live file is gone/empty.
#
# Reboot -f does not wipe Motor/USALS (validated 2026-08-12). This script is a
# safety net for a missing/corrupt DB, not a MotorSettingReinit merge.

TOOLS="/data/freeze_tools"
LIVE="/data/gx/live_prog"
BAK="/data/live_prog_usals_ok.bak"
GOOD="$TOOLS/live_prog.last_good"
LOG="$TOOLS/freeze_watch.log"

log() {
    echo "$(date 2>/dev/null) $*" >> "$LOG" 2>/dev/null
}

src=""
if [ -s "$GOOD" ]; then
    src=$GOOD
elif [ -s "$BAK" ]; then
    src=$BAK
fi

if [ -s "$LIVE" ]; then
    exit 0
fi

if [ -z "$src" ]; then
    log "motor_boot_restore: live_prog missing and no backup"
    exit 0
fi

mkdir -p /data/gx 2>/dev/null
cp "$src" "$LIVE"
sync
log "motor_boot_restore: restored live_prog from $src"
exit 0
