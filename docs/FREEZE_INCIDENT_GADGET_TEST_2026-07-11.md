# Freeze Incident — Lazy-Gadget Runtime Prototype (2026-07-11)

## Summary
During the **Runtime Prototype (Step 2/3)** of the lazy `g_service` work, the receiver
froze (no telnet, user reported picture hung). A full **power-cycle recovered it to a
clean baseline**. No persistent boot changes had been made.

## Timeline
1. Deployed `/usr/bin/gadgetctl` (inert helper). OK.
2. Snapshot: `g_service` rc0; `u_service` held by `hi_dvb,hisi_sci`; stack healthy.
3. `gadgetctl down` → `rmmod g_service` **succeeded**; immediately-following `lsmod`
   returned normally and showed Live-TV transport intact
   (`u_service 2`, `usb_f_service 5`, `libcomposite 1`, `hi_dvb 17`, `hi_demux`, `vtunerc`).
   → The rmmod itself did NOT visibly break anything at that instant.
4. Shortly after, the box became unresponsive. Root cause: **several concurrent
   full-rootfs `find /` + `strings` probe sessions were still running** on a low-memory
   embedded box, in parallel with the gadget test → CPU/IO/mem starvation → hang.
5. User power-cycled. Device booted, **firmware auto-reloaded g_service** (rc0), Live TV
   returned. Post-reboot verify: full stack healthy, `udc_hisi` present.

## Root Cause (honest assessment)
- **Primary:** operator error — I allowed 3–4 heavy recursive scans to run
  simultaneously on the device. This alone can wedge a box this small.
- **Cannot fully exclude:** a delayed interaction from `rmmod g_service` while the
  overloaded box was mid-scan. The clean lsmod at step 3 argues against rmmod being the
  trigger, but we did not get an isolated measurement, so we treat it as *unproven-safe*
  until repeated cleanly.

## What was NOT damaged
- No init script / blacklist / boot hook was installed. `g_service` is auto-loaded by the
  firmware at boot → power-cycle = guaranteed clean recovery.
- `/usr/bin/gadgetctl` is inert (only acts when explicitly invoked) and has hard guards
  that refuse to touch `u_service/usb_f_service/libcomposite/udc_hisi/hi_dvb/hisi_sci`.

## Hard Rules Going Forward (device-safety)
1. **NEVER** run recursive `find /` or `strings` over large trees on the device.
   Scope every probe to a specific dir (e.g. `/data/gx`) and run **one session at a time**.
2. **One telnet session at a time.** The box has very few slots; overlapping sessions
   both starve it and corrupt each other (we saw ConnectionReset cascades).
3. Any live module operation must be a **single isolated action** with an idle box —
   no background jobs running.
4. Keep `gadgetctl up` reachable as instant rollback; power-cycle is the ultimate rollback.

## Status
- Device: **healthy, baseline restored.**
- Lazy-gadget experiment: **paused** pending user decision on whether to repeat the
  down/up cycle *in isolation* (clean box, single session) or to stop live testing.

---

## UPDATE — Isolated retest (2026-07-11, 2nd freeze) — ROOT CAUSE CORRECTED

User approved repeating the down→up cycle **in full isolation**: single telnet
connection, idle box, ZERO concurrent scans/jobs. Result:

```
=== SNAPSHOT (before) ===  g_service rc0, transport healthy, NONCORE=391
=== STEP down (rmmod g_service only) ===
gadgetctl down
[gadgetctl] USB Gadget releasing
<CONNECTION FORCIBLY RESET AT THIS EXACT MOMENT>
```

Follow-up single gentle liveness probe (`tools/liveness_once.py`, one connect, no
retries) => **DEAD: cannot connect => box hung.**

### CORRECTED ROOT CAUSE
My earlier "concurrent scans caused the freeze" conclusion was **WRONG**. With
everything isolated and idle, **`rmmod g_service` BY ITSELF wedges the kernel.**
The concurrent scans in the first incident were a red herring (they made recovery
messier, but were not the trigger).

### HARD CONCLUSION — do NOT remove g_service at runtime
- `rmmod g_service` is **unsafe on this hardware** (hi3798, k4.4.176). It reliably
  hangs the box even though `refcnt=0` and no visible holder. Likely an unsafe
  module-exit path / shared UDC state with the composite stack that only manifests
  on unbind.
- **Runtime `rmmod g_service` is now BLACKLISTED.** `gadgetctl down` must not be used
  on this device again.
- The lazy-init goal (if still wanted) must be achieved a **different** way — e.g.
  preventing g_service from ever loading at boot (blacklist / boot-time), NOT
  unloading it live. That must be validated with serial console + a guaranteed
  recovery path, since telnet dies with the box.

### Recovery
Power-cycle required again (full power removal ~10s). g_service auto-loads at boot →
clean restore. No persistent changes were made.
