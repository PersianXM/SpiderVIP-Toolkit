#!/bin/sh
# freeze_dump.sh — write a durable forensic snapshot under /data/freeze_snap/<ts>/
# Busybox/ash friendly. Safe: read-only probes + writes only under /data.
#
# Usage: freeze_dump.sh <reason>
#   reason: manual | watch | unknown

REASON="${1:-unknown}"
BASE="/data/freeze_snap"
TOOLS="/data/freeze_tools"

# Avoid overlapping dumps
LOCK="$TOOLS/dump.lock"
if [ -f "$LOCK" ]; then
    age=$(( $(date +%s) - $(cat "$LOCK" 2>/dev/null || echo 0) ))
    if [ "$age" -lt 120 ] 2>/dev/null; then
        echo "DUMP_SKIPPED busy age=${age}s"
        exit 0
    fi
fi
mkdir -p "$TOOLS" "$BASE" 2>/dev/null
date +%s > "$LOCK" 2>/dev/null

TS=$(date +%Y%m%d_%H%M%S 2>/dev/null || echo "ts_$$")
DIR="$BASE/$TS"
mkdir -p "$DIR" || { rm -f "$LOCK"; echo "DUMP_FAIL mkdir"; exit 1; }

# Early marker so operators know a snap is in progress (survives if dump is killed)
{
    echo "SNAPSHOT=$DIR"
    echo "REASON=$REASON"
    echo "TAGS: IN_PROGRESS"
    echo "NOTE=Dump running; wait for TAGS without IN_PROGRESS before power-cut."
} > "$DIR/SUMMARY.txt"
sync

# Bounded reads — some /proc/msp nodes return EAGAIN or block
grab() {
    # $1=src $2=dst
    head -c 131072 "$1" > "$2" 2>&1 || echo "grab_fail:$1" >> "$2"
}

{
    echo "reason=$REASON"
    echo "ts=$TS"
    date 2>/dev/null
    echo "--- uptime ---"
    uptime 2>/dev/null
    echo "--- loadavg ---"
    cat /proc/loadavg 2>/dev/null
    echo "--- cmdline ---"
    cat /proc/cmdline 2>/dev/null
} > "$DIR/meta.txt" 2>&1

ls /proc/msp > "$DIR/msp_ls.txt" 2>&1

grab /proc/msp/avplay00 "$DIR/avplay.txt"
grab /proc/msp/sync00 "$DIR/sync.txt"
grab /proc/msp/adec00 "$DIR/adec.txt"
grab /proc/msp/hdmi0 "$DIR/hdmi.txt"
grab /proc/msp/sound0 "$DIR/sound.txt"
grab /proc/msp/demux_main "$DIR/demux_main.txt"
grab /proc/msp/disp0 "$DIR/disp0.txt"
grab /proc/msp/chip_temp "$DIR/chip_temp.txt"

# IRQ rate: two short samples (~2s). Prefer head to avoid huge hangs.
{
    echo "=== sample1 ==="
    date 2>/dev/null
    head -c 65536 /proc/interrupts 2>/dev/null
    sleep 2
    echo "=== sample2 ==="
    date 2>/dev/null
    head -c 65536 /proc/interrupts 2>/dev/null
} > "$DIR/irq.txt" 2>&1

{
    echo "=== ps ax ==="
    ps ax 2>/dev/null | head -n 250 || ps 2>/dev/null | head -n 250
    echo "=== D-state ==="
    ps ax 2>/dev/null | grep ' D ' | head -n 80 || true
} > "$DIR/ps.txt" 2>&1

{
    free -m 2>/dev/null || free 2>/dev/null
    echo "--- meminfo ---"
    head -20 /proc/meminfo 2>/dev/null
} > "$DIR/mem.txt" 2>&1

dmesg 2>/dev/null | tail -n 120 > "$DIR/dmesg_tail.txt" 2>&1

{
    echo "=== sizes ==="
    ls -l /data/gx/live_prog /data/gx/local/enigma_db/lamedb \
        /data/gx/local/enigma_db/satellites.xml \
        /data/gx/local/enigma_db/userbouquet.1.tv \
        /data/gx/local/enigma_db/userbouquet.2.tv \
        /data/gx/local/enigma_db/userbouquet.3.tv 2>&1
    echo "=== SERVICE counts ==="
    grep -c '^#SERVICE' /data/gx/local/enigma_db/userbouquet.1.tv 2>/dev/null
    grep -c '^#SERVICE' /data/gx/local/enigma_db/userbouquet.2.tv 2>/dev/null
    grep -c '^#SERVICE' /data/gx/local/enigma_db/userbouquet.3.tv 2>/dev/null
    echo "=== bouquets.tv ==="
    cat /data/gx/local/enigma_db/bouquets.tv 2>/dev/null
    echo "=== live_prog wc ==="
    wc -c /data/gx/live_prog 2>/dev/null
} > "$DIR/db_stat.txt" 2>&1

{
    PID=$(pidof bianbiang 2>/dev/null | awk '{print $1}')
    echo "pidof=$PID"
    if [ -n "$PID" ]; then
        cat /proc/$PID/status 2>/dev/null
        echo "--- wchan ---"
        cat /proc/$PID/wchan 2>/dev/null; echo
        echo "--- cmdline ---"
        tr '\0' ' ' < /proc/$PID/cmdline 2>/dev/null; echo
    fi
    echo "--- bianbiang.sh ---"
    pidof bianbiang.sh 2>/dev/null
} > "$DIR/bianbiang.txt" 2>&1

# Build SUMMARY tags from captured text
TAGS=""
add_tag() { TAGS="$TAGS $1"; }

grep -q 'CurStatus[[:space:]]*:STOP' "$DIR/avplay.txt" 2>/dev/null && add_tag AV_STOP
grep -q 'Vid Enable[[:space:]]*:FALSE' "$DIR/avplay.txt" 2>/dev/null && add_tag VID_DISABLED
grep -q 'VidPid[[:space:]]*:0x1fff' "$DIR/avplay.txt" 2>/dev/null && add_tag VID_PID_NULL
grep -q 'CrtStatus[[:space:]]*:STOP' "$DIR/sync.txt" 2>/dev/null && add_tag SYNC_STOP
grep -qi 'Resource temporarily unavailable' "$DIR/avplay.txt" 2>/dev/null && add_tag AVPLAY_EAGAIN

ls /proc/msp/vdec00 >/dev/null 2>&1 || add_tag NO_VDEC
ls /proc/msp/win0100 >/dev/null 2>&1 || add_tag NO_WIN
ls /proc/msp/adec00 >/dev/null 2>&1 || add_tag NO_ADEC_NODE

UB1=$(grep -c '^#SERVICE' /data/gx/local/enigma_db/userbouquet.1.tv 2>/dev/null || echo 0)
UB2=$(grep -c '^#SERVICE' /data/gx/local/enigma_db/userbouquet.2.tv 2>/dev/null || echo 0)
UB3=$(grep -c '^#SERVICE' /data/gx/local/enigma_db/userbouquet.3.tv 2>/dev/null || echo 0)
# disk looks populated
if [ "${UB1:-0}" -gt 10 ] 2>/dev/null; then
    add_tag DB_DISK_OK
fi

# crude USB IRQ storm hint: look for dwc_otg in irq samples
if grep -q 'dwc_otg' "$DIR/irq.txt" 2>/dev/null; then
    # if load high, tag as possible storm for later offline rate calc
    LA=$(awk '{print $1}' /proc/loadavg 2>/dev/null)
    LAINT=$(echo "$LA" | cut -d. -f1)
    if [ "${LAINT:-0}" -ge 10 ] 2>/dev/null; then
        add_tag USB_IRQ_STORM_SUSPECT
    fi
fi

pidof bianbiang >/dev/null 2>&1 && add_tag BIANBIANG_ALIVE

{
    echo "SNAPSHOT=$DIR"
    echo "REASON=$REASON"
    echo "TAGS:$TAGS"
    echo "UB_SERVICE_COUNTS=$UB1 $UB2 $UB3"
    echo "NOTE=Do not power-cut until this file exists. Pull with tools/freeze_pull.py after recovery."
} > "$DIR/SUMMARY.txt"

sync
rm -f "$LOCK"
echo "DUMP_OK $DIR TAGS:$TAGS"
exit 0
