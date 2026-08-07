# Project B — g_service Smart Lifecycle (Firmware Architecture Optimization)

**Scope:** This is an *architectural optimization*, independent of the freeze RCA
(Project A). Goal: `g_service` stays **Idle by default** and becomes **Active only when a
legitimate USB Device-Mode feature explicitly requires it** — while preserving full
backward compatibility.

**Hard constraints (from user):**
- NO `rmmod` / `insmod` / any dynamic module unload-reload. (`rmmod g_service` is separately
  proven to hang this SoC — see docs/FREEZE_INCIDENT_GADGET_TEST_2026-07-11.md — but even
  independently of that, dynamic module ops are out of scope here.)
- Event-driven state machine: **Idle → Initializing → Active → Releasing → Idle**.
- 100% backward compatible: default runtime behavior must be indistinguishable from today
  for any existing feature that expects the gadget.

---

## 1. Ground truth captured live (read-only, 2026-07-11)

| Fact | Value | Source |
|------|-------|--------|
| Gadget module | `g_service` (LEGACY composite) | `/sys/module/g_service/parameters/*` = idVendor/idProduct/bcdDevice/qlen/iManufacturer/iProduct/iSerialNumber |
| Current bind | **NONE** — `/sys/class/udc/` empty | `ls /sys/class/udc` |
| refcnt / holders | 0 / none | `/sys/module/g_service/{refcnt,holders}` |
| configfs support | **PRESENT** (`/sys/kernel/config/usb_gadget`, empty) | `test -d` |
| USB role now | HOST only (xHCI 1d6b root hubs) | `/sys/kernel/debug/usb/devices` |
| android_usb | ABSENT | `test -d /sys/class/android_usb` |

**Critical implication:** `g_service` is **already effectively dormant** — it is resident in
memory but bound to no UDC and referenced by nobody. "Activation" today is whatever step
attaches it to the device-mode controller (`udc_hisi`). So the lifecycle work is about
**controlling the bind, not the module.**

---

## 2. The mechanism decision (why not the obvious ones)

| Candidate mechanism | Verdict | Reason |
|---------------------|---------|--------|
| `rmmod`/`insmod` g_service | ❌ FORBIDDEN | Out of scope + hangs SoC |
| configfs UDC attr (`echo <udc> > .../UDC`, `echo "" > UDC`) | ⚠️ not directly usable on `g_service` | That attribute exists only for **configfs-created** gadgets; `g_service` is a **legacy** gadget that binds at its own module-init and does not expose a runtime UDC unbind |
| UDC `soft_connect` pullup (`echo disconnect/connect > /sys/class/udc/<udc>/soft_connect`) | ✅ usable when a UDC is bound | Toggles the D+ pull-up: host stops enumerating, but the gadget/module stay intact. Non-destructive, instantly reversible |
| Gate activation at the **loader / feature layer** (don't bind until a feature asks) | ✅ preferred, cleanest | Because the box already sits with no UDC bound, we keep it that way until an event demands device mode |

**Chosen architecture = two complementary layers:**
- **L1 (preferred, structural): a configfs-based gadget** that natively supports
  Idle↔Active via UDC bind/unbind, replacing the legacy `g_service` bind path while keeping
  the *same* USB descriptors/functions for backward compatibility.
- **L2 (compatibility bridge, zero-migration): a soft-connect controller** that, for the
  existing legacy `g_service`, models Idle/Active as pull-up disconnect/connect on the bound
  UDC — no module touch, fully reversible. Used until/if L1 migration is adopted.

Both are driven by the same **event-driven state machine** below, so the policy is identical
regardless of which mechanism is active underneath.

---

## 3. Event-driven state machine

```
        ┌─────────┐  demand(feature X)   ┌──────────────┐  bind ok    ┌────────┐
        │  Idle   │ ───────────────────▶ │ Initializing │ ──────────▶ │ Active │
        └─────────┘                      └──────────────┘             └────────┘
             ▲                                  │ bind fail                │
             │                                  ▼                          │ last consumer
             │            ┌───────────┐   (rollback to Idle)               │ releases +
             └──────────  │ Releasing │ ◀──────────────────────────────────┘ grace timer
                          └───────────┘
```

**States**
- **Idle** — default. No UDC bound (L1) / pull-up disconnected (L2). Zero host-visible device.
  This is the power-on default → *lazy by default*.
- **Initializing** — a legitimate consumer requested device mode. Bring up bind (L1: write UDC)
  or assert pull-up (L2). Guarded + timed.
- **Active** — enumerated & serving. Reference-counted by consumers.
- **Releasing** — last consumer released; a **grace timer** (debounce, e.g. 5–10 s) prevents
  flapping. If a new demand arrives during grace, snap back to Active.
- On any bind/setup failure → deterministic **rollback to Idle** (never leave a half-state).

**Events / API (backward compatible):**
- `demand(feature_id)` → refcount++, triggers Idle→Initializing→Active.
- `release(feature_id)` → refcount--, when 0 triggers Active→Releasing→(grace)→Idle.
- `status()` → current state + refcount + underlying mechanism (L1/L2).
- Legacy callers that assume "gadget is always up" keep working via a **compat policy flag**
  `default_active=1` (see §5) which makes the machine boot straight into Active — identical to
  today's behavior — until the operator opts into lazy mode.

**Legitimate demand sources (examples to wire up):** USB-mass-storage/PVR export request,
ADB/diagnostic service start, DRM/CA provisioning over USB, vendor update-over-USB. Each must
call `demand()`/`release()` around its usage window.

---

## 4. Reference-counting & safety rules
1. Single owner of the mechanism (a small daemon/service) serializes all transitions — no
   concurrent binds.
2. Every transition is **idempotent** and **reversible**; failures roll back to Idle.
3. Never touch the protected transport stack (`u_service/usb_f_service/libcomposite/udc_hisi/
   hi_dvb/hisi_sci`) — those are load-bearing for Live TV.
4. All live validation of bind/unbind or pull-up **must** be done with a serial console
   attached and a guaranteed power-cycle recovery path, one isolated action at a time.
5. No module load/unload — enforced in code (the existing `gadgetctl` already hard-refuses
   `down`/rmmod).

---

## 5. Backward compatibility strategy
- **Config flag `gadget_lifecycle_mode`:**
  - `legacy` (default at first ship) → machine boots to **Active** immediately = byte-for-byte
    current behavior. Ships safe.
  - `lazy` → machine boots to **Idle**, activates on demand. The optimization, opt-in.
- Same USB descriptors, VID/PID, function set, and `qlen` as today (mirror the legacy
  `g_service` module params) → hosts see an identical device when Active.
- Roll-forward/roll-back is a single config value; no firmware surgery to revert.

---

## 6. Implementation plan (staged, safety-gated)
- **B1 (offline, now):** finalize this design + build the state-machine daemon skeleton
  (`gadgetd`) purely in the project tree; unit-test the FSM off-device.
- **B2 (offline):** implement L2 (soft-connect) driver against the FSM; dry-run against
  captured sysfs fixtures. No device.
- **B3 (serial-console gated):** first on-device test of L2 pull-up disconnect/connect while a
  UDC is bound — single isolated action, serial console up, power-cycle ready.
- **B4 (serial-console gated):** prototype L1 configfs gadget mirroring g_service descriptors;
  validate bind/unbind cycle without touching the legacy module at boot.
- **B5:** wire real `demand()/release()` call sites; ship in `legacy` mode; enable `lazy`
  behind the flag after field validation.

**Current status:** B1 design complete (this doc). No on-device state changes were made in
Project B beyond read-only topology capture (`build/cmd_gadget_topo.txt`).
```
```
