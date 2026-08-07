# SpiderVIP receiver: fixing the "no picture / no sound" freeze

Diagnostic and repair guide for the audio/video freeze on SpiderVIP-class
satellite receivers, when every other part of the box still works.

## Symptoms

- Dish/LNB control (DiSEqC / motor / switch) works.
- Channel zapping works.
- Power on/off from the remote works.
- The settings menu opens and renders correctly.
- **Every channel has no picture.**
- **Every channel has no sound.**

## Why the fault is where it is

Because the **settings menu renders correctly**, the SoC, the OSD graphics
plane and the display output (HDMI/AV) are all known good. In an STB the menu is
a graphics plane composited on top of a separate video plane. So if the menu is
visible but channels are black, the fault lives **between the tuner and the
audio/video decoders**, or in the **decode/output stage** — not in the panel or
the SoC.

Losing audio *and* video on *all* channels while zapping still works points to a
single shared upstream fault, not a per-channel or per-codec problem.

## Ranked causes

Ordered by likelihood given these symptoms, cheap remote fix cost, and live
evidence from this repo. Work **P1→P6** first (same order as `spidervip`); then
P7+ if needed.

### Full priority table

| Priority | Cause | Why likely / project evidence | Fix | Remote? |
| --- | --- | --- | --- | --- |
| **P1** | A/V play path stopped / decoder service down | Most common; menu survives separately. Live 2026-08-07: `avplay=STOP`, Vid/Aud disabled, no `vdec00` | Soft-restart player / `bianbiang` (`restart-av-service`) | Yes |
| **P2** | Demux not routing A/V PIDs | Zapping works but TS never reaches VDEC/ADEC; stuck demux or stale PID map | Reset demux + reload PIDs (`reinit-demux`) | Yes |
| **P3** | Video plane off / mixer muted | OSD (GFX) visible; VIDEO plane black or audio `SendCnt=0` | `enable-video-plane`, `unmute-audio` | Yes |
| **P4** | Output format unsupported by TV | Rejected bitstream or video mode outside TV range; OSD stays on a safe mode | Audio `auto`, video `1080p50` | Yes |
| **P5** | Weak signal / lost frontend lock | UI OK; LOCKED weak or zero | LNB, cable, dish | No (manual) |
| **P6** | FTA channel wrongly flagged scrambled | Bad CAS/keys table blanks A/V | Reset CAS/settings on box | No (manual) |
| **P7** | No respawn for `bianbiang` | ISSUE-001: `inittab once` + no loop → any crash = permanent black screen | Supervised loop in `bianbiang.sh` (v1.00.93) | Yes (deploy patch) |
| **P8** | Helper services die without restart | ISSUE-002: `streamrelay` / `satipclient` / `app_console` | Light supervision in `bianbiang.sh` | Yes (deploy patch) |
| **P9** | OOM / memory pressure on long uptime | ISSUE-003: low `min_free`, high dirty → OOM-kill of the app | Safer sysctl + zram if needed | Yes (deploy patch) |
| **P10** | USB gadget / `gservice` TS IRQ storm | Freeze 2026-07-11: load≈14, idle CPU, VDEC/VPSS/network stall | Disable PC-Link/PVR-over-USB; controlled gadget restart | Semi |
| **P11** | HiSilicon chain stall (VDEC/VPSS/win/sync) | Counters frozen; `sync=STOP`; missing `vdec`/`win` nodes | A/V restart; soft reboot if stuck | Yes |
| **P12** | TS transport errors or unlocked frontend | Demux up but stream empty/corrupt | Physical signal + demux reset | Mixed |
| **P13** | Corrupt channel DB (`live_prog` / bad PIDs) | After incomplete scan or `satellites.xml` mismatch | Repair DB; commit via WebIF | Manual |
| **P14** | Bad patch/firmware on the A/V path | UI survives, decode breaks | Roll back patch / restore backup | Manual |

`spidervip` auto-handles P1–P6 today. P7–P11 come from this repo's stability
audit and live forensics.

### Lab observation (2026-08-07)

| Stage | State |
| --- | --- |
| `bianbiang` | Running |
| HDMI / OSD | Connected, active |
| `avplay00` | **STOP** — video and audio disabled |
| Video decoder | No `vdec00` node |
| Audio | Mute off but `SendCnt=0` |
| Closest label | **P1** (play path stopped); also check **P10** if USB load stays high |

## Recommended fix for the current lab fault

Low risk → higher risk; **no full flash**:

1. **Confirm on the TV:** stay on a satellite channel (not only the menu); zap once.
   If `avplay` leaves STOP after a zap, it was transient.
2. **Soft-restart playback (P1):** over Telnet stop `bianbiang` once so
   `bianbiang.sh` respawns it; after 30–60s re-read `/proc/msp/avplay00` —
   `CurStatus` should not be STOP and the video PID should not be `0x1fff`.
3. **Still STOP — demux/PIDs (P2):** reset demux and zap the same channel again.
4. **Video plane / unmute (P3)**, then safe HDMI modes (P4) if needed.
5. **USB gadget (P10):** if load stays ~14 and `dmesg` shows a `service gadget`
   storm, disable PC-Link / USB TS streaming in the menu.
6. **Signal / CAS (P5/P6):** only after `avplay` is RUN again but A/V is still dead.
7. **Last soft step:** remote `reboot`. A full `.mupg` flash is not required unless
   a known-bad patch is installed.

Sample commands for step 2 (from repo root, only after you approve):

```powershell
# example cmds.txt — run only after approval
# killall bianbiang
# sleep 3
# pidof bianbiang
# cat /proc/msp/avplay00 | head -40
```

## Before power-cut — mandatory forensics

A hard power-cut resets SoC/MMZ and often clears the symptom, but it also
**wipes the runtime evidence**. Do not pull power until a durable snapshot exists
under `/data`.

### One-time watcher deploy

```powershell
python tools/deploy_freeze_watch.py
```

Installs under `/data/freeze_tools/` and hooks `/home/gx/local/user_script` (already
called from `bianbiang.sh`) so the watcher returns after boot. When the freeze
signature holds (~60s of `avplay=STOP` with `bianbiang` alive), it writes
`/data/freeze_snap/<timestamp>/` automatically.

### When you see a freeze right now

```powershell
python tools/freeze_capture.py
```

Wait for `DUMP_OK` and `SUMMARY.txt`. **Only then** is a power-cut allowed.

### After the box is back

```powershell
python tools/freeze_pull.py          # latest snap → build/freeze_snap/
python tools/freeze_pull.py --list
```

Each snapshot includes `avplay`/`sync`/`irq`/`ps`/`dmesg`/`db_stat`/`SUMMARY.txt`
with tags such as `AV_STOP`, `NO_VDEC`, `USB_IRQ_STORM_SUSPECT`, `DB_DISK_OK`.

## Repair over the online connection

### Live access on the lab Spider VIP

On this repo's lab box (`clap4k`), the primary path is **Telnet on port 23**;
SSH is usually closed. Full IP/login/tooling guide:

- [`NETWORK_ACCESS_GUIDE.md`](NETWORK_ACCESS_GUIDE.md)

Quick check:

```powershell
ping -n 2 192.168.100.102
Test-NetConnection 192.168.100.102 -Port 23
python tools/telnet_run.py cmds.txt
```

Login: `root` / `root` at `192.168.100.102` (re-check IP if DHCP changed).

### `spidervip` toolkit (SSH backend)

`spidervip` reads the A/V pipeline state, applies fixes in priority order, and
re-checks picture/sound after each one. Its online backend uses **SSH +
paramiko**. If your box only has Telnet, use `tools/telnet_*.py` for live work,
or `--simulate` without hardware.

### Prerequisites (when SSH is available)

- Receiver reachable on the LAN; know its IP.
- For the online SSH backend: `pip install paramiko`.

### Commands

```bash
spidervip diagnose --host 192.168.1.50 --user root --password ****** --profile enigma2
spidervip repair   --host 192.168.1.50 --user root --password ****** --profile enigma2
spidervip repair   --host 192.168.1.50 --dry-run          # plan only
```

If your box does not match the `enigma2` profile, try `linux-stb` or adapt the
shell commands in `spidervip/ssh_receiver.py`.

### Simulator (learn/test without hardware)

```bash
spidervip faults
spidervip diagnose --simulate --fault player-crash
spidervip repair   --simulate --fault demux-stuck --fault audio-muted
```

## Recommended flow

1. Walk the priority table from P1 downward; on Telnet boxes start by reading
   `/proc/msp/avplay00`.
2. Run `spidervip diagnose` / `repair` when SSH is available; otherwise apply the
   same order with `tools/telnet_run.py`.
3. `picture OK, sound OK` (or `avplay` in RUN with a real video PID) means cleared.
4. P5/P6/P12–P14 need manual/physical steps per the table above.

## Record for future use

- Save `diagnose`/`repair` output (use `--json`) per device to keep a history.
- When you adapt shell commands for a new model, add that `ReceiverProfile` to
  `spidervip/ssh_receiver.py` so it is ready next time.
