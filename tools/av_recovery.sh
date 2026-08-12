#!/bin/sh
# av_recovery.sh — on-box recovery for MSP play-path wedge (validated 2026-08-12).
#
# After freeze_watch has held the freeze signature for HOLD_SEC:
#   backup live_prog, then /sbin/reboot -f
#
# Safety: AUTO_RECOVERY=1, no DISABLE file, boot grace, max recoveries/day.
# Does not zap a channel (firmware resumes last service).
# Does not rmmod g_service. Does not killall bianbiang.

TOOLS="/data/freeze_tools"
# shellcheck disable=SC1091
. "$TOOLS/freeze_lib.sh"
freeze_load_conf

mkdir -p "$TOOLS" 2>/dev/null

if ! freeze_recovery_allowed; then
    echo "RECOVERY_SKIPPED"
    exit 0
fi

freeze_log "recovery start: backup live_prog then reboot -f"
freeze_backup_live_prog
echo "$(freeze_now) reboot-f uptime=$(freeze_uptime_sec)" >> "$RECOVERY_LOG"
sync

echo "RECOVERY_REBOOT"
# Validated: plain `reboot` from this firmware did not reboot the lab box.
/sbin/reboot -f
# If reboot -f returns (should not), try once more then exit.
sleep 2
/sbin/reboot -f
exit 0
