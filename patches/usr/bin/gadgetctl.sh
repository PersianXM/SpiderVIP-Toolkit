#!/bin/sh
# gadgetctl — lazy lifecycle controller for the Spider VIP USB Device-Mode gadget.
#
# SCOPE / SAFETY:
#   This tool operates ONLY on the idle device-mode gadget module `g_service`.
#   It MUST NEVER touch u_service / usb_f_service / libcomposite / udc_hisi,
#   because on this box those are held by hi_dvb (Live TV) + hisi_sci (CA reader)
#   and are load-bearing for satellite reception. See docs/LAZY_GADGET_DESIGN.md.
#
# Commands:
#   gadgetctl status     -> print current state (Idle/Active/…)
#   gadgetctl up         -> lazily bring the gadget up (insmod g_service)
#   gadgetctl down       -> release the gadget (rmmod g_service ONLY)
#   gadgetctl guard      -> verify Live-TV transport modules are still intact
#
# State file for the engineering dashboard:
STATE_FILE=/tmp/usb_gadget_state
GADGET_KO=/lib/modules/4.4.176/extra/g_service.ko
GADGET_MOD=g_service
# Modules that must be protected at all costs (never unloaded by this tool):
PROTECTED="u_service usb_f_service libcomposite udc_hisi hi_dvb hisi_sci"

log()   { echo "[gadgetctl] $*"; logger -t gadgetctl "$*" 2>/dev/null; }
setst() { echo "$1" > "$STATE_FILE" 2>/dev/null; }

is_loaded() { grep -q "^$1 " /proc/modules 2>/dev/null; }

# Refuse to run if the protected transport stack is missing (that would mean
# something already broke Live TV — we must not make it worse).
guard() {
  for m in u_service usb_f_service; do
    if ! is_loaded "$m"; then
      log "GUARD FAIL: protected module '$m' not loaded — refusing to act"
      return 1
    fi
  done
  # never allow this tool to be tricked into touching a protected module
  case " $PROTECTED " in
    *" $GADGET_MOD "*) log "GUARD FAIL: gadget module is in protected list"; return 1;;
  esac
  return 0
}

status() {
  if is_loaded "$GADGET_MOD"; then
    rc=$(cat /sys/module/$GADGET_MOD/refcnt 2>/dev/null)
    if [ "$rc" = "0" ]; then st="Loaded-Idle"; else st="Active"; fi
  else
    st="Idle"
  fi
  # if a state file exists and is transitional, prefer it
  [ -r "$STATE_FILE" ] && fst=$(cat "$STATE_FILE" 2>/dev/null)
  case "$fst" in Initializing|Releasing) st="$fst";; esac
  echo "USB Gadget: $st"
}

up() {
  guard || return 1
  if is_loaded "$GADGET_MOD"; then
    log "gadget already present"; setst "Active"; return 0
  fi
  setst "Initializing"; log "USB Gadget initializing"
  if insmod "$GADGET_KO" 2>/dev/null; then
    setst "Active"; log "USB Gadget session started"
  else
    setst "Idle"; log "USB Gadget insmod FAILED"; return 1
  fi
}

down() {
  # !!! BLACKLISTED 2026-07-11 !!!
  # Isolated testing proved `rmmod g_service` hangs the kernel on this hardware
  # (hi3798, k4.4.176) even with refcnt=0. See docs/FREEZE_INCIDENT_GADGET_TEST.
  # This command is permanently disabled to protect the device.
  log "REFUSING: 'down' (rmmod g_service) is BLACKLISTED — it wedges the box"
  echo "gadgetctl down is DISABLED (unsafe on this hardware)"; return 3
  guard || return 1
  if ! is_loaded "$GADGET_MOD"; then
    log "gadget already idle"; setst "Idle"; return 0
  fi
  rc=$(cat /sys/module/$GADGET_MOD/refcnt 2>/dev/null)
  if [ "$rc" != "0" ]; then
    log "gadget busy (refcnt=$rc) — a session is active, not releasing"; return 1
  fi
  setst "Releasing"; log "USB Gadget releasing"
  if rmmod "$GADGET_MOD" 2>/dev/null; then
    setst "Idle"; log "USB Gadget released"
  else
    setst "Loaded-Idle"; log "USB Gadget rmmod FAILED"; return 1
  fi
}

case "$1" in
  status) status ;;
  up)     up ;;
  down)   down ;;
  guard)  guard && echo "guard OK: transport stack intact" ;;
  *) echo "usage: gadgetctl {status|up|down|guard}"; exit 2 ;;
esac
