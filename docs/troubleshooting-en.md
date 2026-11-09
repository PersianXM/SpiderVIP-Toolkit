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
| **P11** | HiSilicon chain stall (VDEC/VPSS/win/sync) | Counters frozen; `sync=STOP`; missing `vdec`/`win` nodes | A/V restart; soft reboot if stuck | Yes |
| **P12** | TS transport errors or unlocked frontend | Demux up but stream empty/corrupt | Physical signal + demux reset | Mixed |
| **P13** | Corrupt channel DB (`live_prog` / bad PIDs) | After incomplete scan or `satellites.xml` mismatch | Repair DB; commit via WebIF | Manual |
| **P14** | Bad patch/firmware on the A/V path | UI survives, decode breaks | Roll back patch / restore backup | Manual |

`spidervip` auto-handles P1–P6 today. P7–P11 come from this repo's stability
audit and live forensics.

## Confirmed cause and recovery (November 2026)

The "menu works, no picture or sound on any channel" freeze was captured live twice (2026-11-02 and 2026-11-09). Both times the cause was a stuck lock in the audio output driver (`hi_aiao.ko`): audio stops, the demux audio channel fills, and the demux then stops reading its input. USB/`g_service` is a victim in this chain, not the cause. Details: [`freeze/AUDIO_FREEZE_2026-11.md`](freeze/AUDIO_FREEZE_2026-11.md).

- **Automatic recovery:** install the on-box watchdog by double-clicking `PATCH_RECEIVER.bat`; `CHECK_RECEIVER.bat` shows its status.
- **Manual recovery:** [`freeze/AV_RECOVERY_RUNBOOK-en.md`](freeze/AV_RECOVERY_RUNBOOK-en.md) (`/sbin/reboot -f`).
- **Before cutting power:** if the box is still on the network, run `python tools/freeze_state.py` to save a read-only snapshot in `build/freeze_state/`.

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
shell commands in `spidervip/freeze/ssh_receiver.py`.

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
  `spidervip/freeze/ssh_receiver.py` so it is ready next time.
