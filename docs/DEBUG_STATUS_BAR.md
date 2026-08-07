# Engineering Debug Status Bar (dbgbar)

A permanent, lightweight, real-time health overlay for the Spider VIP
(HiSilicon) receiver. It lets a developer read CPU/thermal/decoder/DEMUX/USB/
network/storage state **directly on the TV screen — no SSH/Telnet required.**

---

## 1. Why an OSD overlay (and not "edit the Main Menu")

The Main-Menu UI is the compiled proprietary binary `bianbiang` (PID 1466 on
the live box). Its top-right widgets (weather, BT, Wi-Fi, date, time) are drawn
from inside that binary and cannot be modified without full reverse-engineering
of a closed application — which is fragile and would break on every firmware
update.

Instead, the receiver exposes **two hardware OSD layers** (verified live):

| Node        | Layer      | Format    | Size       | Used by            |
|-------------|-----------|-----------|------------|--------------------|
| `/dev/fb0`  | hifb0      | ARGB8888  | 1920×1080  | main UI (bianbiang)|
| `/dev/fb1`  | **hifb1**  | ARGB8888  | 1920×1080  | **free — our bar** |

`hifb1` is a separate hardware layer that the SoC **alpha-blends over** the main
UI. We paint only a thin strip at the top; the rest of the layer stays fully
transparent (`A=0`). Result:

- The bar appears to be a natural extension of the existing status area.
- We **never cover or overlap** existing menu items (we own a different plane).
- We **never touch** `bianbiang`, so firmware updates can't conflict with logic.
- It is **permanently available** from every screen, including the Main Menu.

---

## 2. Architecture (modular providers → snapshot → renderer)

```
              ┌──────────────────────────────────────────────┐
              │                 main.c (loop)                │
              │  epoll( timerfd[refresh] , /dev/input/event0 )│
              └───────────────┬───────────────┬──────────────┘
                              │ tick          │ remote keys
                              ▼               ▼
   ┌───────────── providers.c ─────────────┐   seq: MENU+9999
   │ TemperatureProvider   CpuLoadProvider │      → toggle eng_mode
   │ MemoryProvider        UptimeProvider  │
   │ AvPipelineProvider (VDEC/ADEC/DEMUX)  │        writes into
   │ SignalProvider        NetworkProvider │   ┌──────────────────┐
   │ USBProvider           StorageProvider │──▶│  metrics_t (one  │
   │ EngineeringProvider                   │   │  shared snapshot)│
   └───────────────────────────────────────┘   └────────┬─────────┘
                                                         │ read-only
                                                         ▼
                                              ┌────────────────────┐
                                              │  render.c → /dev/fb1│
                                              │  (consumes metrics; │
                                              │   NO logic inside)  │
                                              └────────────────────┘
```

- **Each display item is an independent provider** (`provider_t` in `dbgbar.h`)
  with a `sample(metrics_t*, config_t*)` function. Add/remove one line in the
  `g_providers[]` registry to add/remove a metric.
- **GUI widgets consume provider output only.** `render.c` contains zero
  data-collection logic — it just formats `metrics_t` fields into colored
  segments. This is the "no business logic inside GUI" rule.

### Files
```
patches/usr/local/dbgbar/
  dbgbar.h      shared types: metrics_t, config_t, provider_t + prototypes
  font8x8.h     embedded 8x8 bitmap font (no external font dependency)
  providers.c   all metric providers (read /proc/hisi/msp/*, /proc, /sys)
  render.c      ARGB8888 strip renderer on /dev/fb1, thermal colors, blink
  config.c      /data/dbgbar.conf parser (clamped, safe defaults)
  main.c        epoll event loop, MENU+9999 shortcut, hot-reload, clean exit
  Makefile      cross-compile (override CROSS=...)
patches/data/dbgbar.conf   default configuration
patches/usr/bin/bianbiang.sh   launch hook (start_services, supervised)
```

---

## 3. Data sources (all verified live on the device)

| Item              | Source                                   | Notes |
|-------------------|------------------------------------------|-------|
| CPU Temp          | `/proc/hisi/msp/chip_temp`               | "Chip Temperature : 77" |
| CPU Load          | `/proc/stat` (idle/total delta)          | true utilization, not loadavg* |
| CPU Freq          | `/sys/.../cpufreq/scaling_cur_freq`      | eng-mode |
| RAM               | `/proc/meminfo` (MemAvailable)           | used% |
| Uptime            | `/proc/uptime`                           | Nd Nh |
| VDEC / codec / res / fps | `/proc/hisi/msp/vdec00`, `.../stat` | FRAMEDECED advance = OK; stall≥3 = HANG |
| ADEC              | `/proc/hisi/msp/stat` ASTART/ASTOP       | |
| DEMUX             | `.../stat` STREAMIN, `.../demux_chanbuf` | overflow/underflow |
| PTS / PCR / buffer | `/proc/hisi/msp/avplay00`, `demux_chanbuf` | eng-mode |
| Signal SNR/AGC/BER | `/proc/stb/frontend/0/{snr,agc,ber}`    | graceful `--` if absent |
| Network           | `SIOCGIFADDR` eth0/wlan0, `/proc/net/dev`| kind, IP, throughput |
| USB Gadget        | `/proc/interrupts` dwc_otg + configfs    | **STREAM** if TS export active |
| Storage           | `statvfs("/")`, USB/HDD mounts           | used%, free MB |
| HDMI/HDCP/color   | `/proc/hisi/msp/hdmi0*`                   | eng-mode |

\* **Important design note:** we deliberately use `/proc/stat` utilization for
"CPU Load", **not** `loadavg`. On this HiSilicon platform loadavg sits at ~13–14
at idle because ~14 AV-pipeline kernel threads live permanently in D-state
(documented in `FREEZE_ROOT_CAUSE_ANALYSIS.md`). Showing loadavg would be a
constant false alarm; true utilization (CPU ~3–9%) is the honest metric.

---

## 4. Display items & states (per spec)

- 🌡 **CPU 61°C** — thermal, color-zoned (see §6)
- ⚡ **CPU 18%** — utilization
- 💾 **RAM 43%** — used memory
- ⏱ **3d 18h** — uptime
- **VDEC OK / HANG / RST** — green / red / yellow
- **ADEC OK / STOP / ERR**
- **DMX OK / WAIT / ERR / OVFL / UNFL**
- 📡 **SIG 91% B0** — SNR% + BER
- Codec: **H264 / HEVC / MPEG2 / AVS**
- Resolution+rate: **1080i / 1080p / 2160p**, **50Hz/25fps**
- Network: **LAN / WiFi / DISC** + IP
- USB Gadget: **USB:STREAM** (TS export active) / **USB:IDLE**
- Storage: **FL:xx%** internal flash (+ USB/rec free)

Missing/unavailable value → **`--`** (never crash, never block).

---

## 5. Engineering Mode (advanced diagnostics)

Toggle live with the hidden remote shortcut **MENU then 9 9 9 9** (a 3s
inter-key timeout resets capture; any other key cancels). Adds a 2nd row:

`DEC:<decoded>  BUF:<fill%>  PTS  PCR  IRQ:<rate>/s  <MHz>  HDMI:UP  HDCP  <mV>`

Also settable persistently via `eng_mode=1` in the config.

---

## 6. Temperature warning zones

| Zone      | Threshold | Color   | Behaviour           |
|-----------|-----------|---------|---------------------|
| Normal    | < 65 °C   | green   | —                   |
| Yellow    | ≥ 65 °C   | yellow  | —                   |
| Orange    | ≥ 70 °C   | orange  | —                   |
| Red       | ≥ 75 °C   | red     | `! HOT !` tag       |
| Critical  | ≥ 80 °C   | red     | **flashing** strip + `! CRITICAL TEMP !` |

---

## 7. Configuration page

`/data/dbgbar.conf` is a plain `key=value` file, **hot-reloaded** within one
tick (no restart). Keys:

- `enabled` (0/1), `eng_mode` (0/1)
- `refresh_sec` = 1 | 2 | 5 | 10
- `style` = compact | normal | developer
- per-widget: `w_temp w_cpu w_ram w_uptime w_vdec w_adec w_dmx w_signal
  w_codec w_res w_net w_gadget w_storage`

> To wire this into the enigma2/GUI Settings menu, add a simple ConfigList
> plugin page that writes these keys; the daemon picks up changes automatically.
> (The file-based contract keeps the daemon decoupled from any specific UI.)

---

## 8. Performance & safety guarantees (how each requirement is met)

| Requirement                    | How it is guaranteed |
|--------------------------------|----------------------|
| CPU < 0.5%                     | one wakeup / refresh_sec; each cycle = a handful of small `/proc` reads + a ~1900×32px blit. Idle time spent blocked in `epoll_wait`. |
| Memory < 2 MB                  | static/stack buffers only; the only large mapping is the shared fb1 the kernel already allocates (we `mmap`, not copy). RSS is a few hundred KB. |
| No busy polling               | `epoll_wait(-1)` + `timerfd`; never spins. |
| Event-driven / reuse timers   | single `timerfd`; remote handled via `epoll` on `event0`. |
| Never block GUI thread        | separate process, separate OSD layer; no IPC with `bianbiang`. |
| No per-refresh allocation      | zero `malloc` in the hot path (grep: none in providers/render). |
| Never interfere with Live TV   | only reads `/proc`; draws to fb1, not the video plane. |
| Never raise temperature        | negligible CPU; no polling; no GPU use. |
| Never crash / freeze           | every read is a bounded one-shot; failures → `--`; loop is exception-free. |

---

## 9. Build & deploy

### Cross-compile
```sh
cd patches/usr/local/dbgbar
make CROSS=arm-linux-gnueabihf-     # or your HiSilicon toolchain prefix
# produces stripped ./dbgbar (a few tens of KB)
```

### Install onto the receiver (over the existing service-gadget network)
```sh
# copy binary + config
scp dbgbar            root@192.168.100.102:/usr/local/dbgbar/dbgbar
scp ../../../data/dbgbar.conf root@192.168.100.102:/data/dbgbar.conf
ssh root@192.168.100.102 'chmod +x /usr/local/dbgbar/dbgbar'

# start now (no reboot needed)
ssh root@192.168.100.102 '/usr/local/dbgbar/dbgbar &'
```
The `bianbiang.sh` hook starts it automatically on every subsequent boot and
respawns it if it exits.

### Bake into firmware
Place the tree under `patches/` into the rootfs image before repacking the
`.mupg` (same overlay mechanism already used by this project), then rebuild the
firmware. The launch hook is already in `patches/usr/bin/bianbiang.sh`.

---

## 10. Validation checklist (72-hour soak)

Run these while the bar is active; all must hold:

- [ ] **No GUI lag** — navigate menus; input latency unchanged (bar is a
      separate plane, no IPC).
- [ ] **CPU overhead** — `top -bn2` delta for `dbgbar` < 0.5%.
- [ ] **Memory** — `cat /proc/$(pidof dbgbar)/status | grep VmRSS` stable < 2 MB
      across 72 h (no leak: zero hot-path allocation).
- [ ] **No frame drops** — `/proc/hisi/msp/stat` FRAMEDECED continues to rise;
      no new VSTOP events attributable to the bar.
- [ ] **No extra interrupts** — `/proc/interrupts` vdec/vdp/aiao deltas unchanged
      vs. baseline; dbgbar adds no IRQ source.
- [ ] **No temperature increase** — `/proc/hisi/msp/chip_temp` before/after ≈ equal.
- [ ] **Stable after 72 h** — process still alive (`pidof dbgbar`), overlay
      correct, config hot-reload still working.

A helper script for the soak test can drive these reads over the existing
telnet channel (see `tools/telnet_run.py`).

---

## 11. Extending

Add a new metric in three steps:
1. Add fields to `metrics_t` in `dbgbar.h`.
2. Write a `static void xxx_sample(metrics_t*, const config_t*)` in
   `providers.c` and register it in `g_providers[]`.
3. Emit a segment for it in `build_segments()` (or `build_eng_segments()`).

No other file needs to change — that is the point of the provider model.

---

## LIVE VALIDATION RESULT (2026-07-11)

The debug status bar was cross-compiled, deployed, and verified on the live
receiver at 192.168.100.102 (root/telnet).

### Build
- Toolchain: portable Zig 0.16.0 zig cc, target rm-linux-musleabihf,
  -mcpu=cortex_a7 -Os -static -> fully static musl ELF, no runtime deps.
- Output: `dbgbar` 57,964 bytes, ELF 32-bit ARM (machine 0x28).
- Reproduce: `python tools/build_dbgbar.py`
- Final artifact: `build/dbgbar.arm`  MD5 `5CA9DFDA6538548C2DFF32BCC1FE3321`

### Deploy
- `python tools/deploy_dbgbar.py` pushes the binary (base64 in 2 KB chunks)
  to `/usr/local/dbgbar/dbgbar` and the config to `/data/dbgbar.conf`,
  then launches the daemon. On-device md5 matches host md5.

### Runtime (measured on device)
- Process alive, `State: S (sleeping)`, `Threads: 1` (epoll-driven, no busy poll).
- `VmRSS = 80 kB` resident (target was < 2 MB) - excellent.
- `VmPeak = 8328 kB` == the 1920x1080x4 fb1 mmap, confirming the overlay
  framebuffer is mapped.
- fb1 top strip: 44,612 / 122,880 pixels non-zero (36.3%) - the bar renders.

### Rendered output (captured from /dev/fb1)
`T:78C  CPU:4%  RAM:37%  UP:001H  VDEC HANG  ADEC OK  DMX OVFL  H264 1080i  WiFi 192.168.100.102  USB:IDLE  FL:90%`
- Screenshot pulled to `build/dbgbar_fb1.png` (via `tools/pull_png.py`).

### Bug found & fixed during validation
- Temperature first showed `T:0C`. Root cause: `/proc/hisi/msp/chip_temp`
  starts with an ASCII-art header line `---------Hisilicon Chip Temperature
  Info---------`; `grab_long` treated the leading `-` dashes as a negative
  sign and parsed 0. Fixed so a `-` only counts as a sign when a digit
  immediately follows; lone dashes are skipped. After rebuild+redeploy the bar
  correctly shows `T:78C` in red (>=75C zone), confirming both the parse fix
  and the temperature colour-zone logic.

### Status: VALIDATED ON HARDWARE
The daemon is ready to be baked into the customized firmware image; the hook in
`patches/usr/bin/bianbiang.sh` launches it at boot.
