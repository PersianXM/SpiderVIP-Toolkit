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

Ordered by how to work them (top = try first). Ranking reflects likelihood given
these exact symptoms and how cheaply the fix can be applied remotely.

| Priority | Cause | Why likely | Remote fix | Auto |
| --- | --- | --- | --- | --- |
| P1 | A/V decoder service crashed / never started | Most common after a bad patch/firmware; the menu survives because the UI is a separate process | Restart the player service (`restart-av-service`) | Yes |
| P2 | Demux not routing audio/video PIDs to decoders | Channel is locked (zapping works) but the transport stream never reaches the decoders; stuck demux or stale PID map | Reset demux + reload PID map (`reinit-demux`) | Yes |
| P3 | Video plane disabled / audio muted at mixer | Video layer switched off or output mixer muted | Enable video plane, unmute audio (`enable-video-plane`, `unmute-audio`) | Yes |
| P4 | Output A/V format not supported by the TV | Bitstreaming a codec the TV rejects, or a video mode outside the TV's range | Set safe output (audio `auto`, video `1080p50`) | Yes |
| P5 | Weak signal / lost lock | Weak signal can drop A/V while the UI keeps working | Check LNB power, cable, dish alignment — not fixable in firmware alone | No |
| P6 | FTA channel wrongly flagged scrambled | Corrupted CAS/keys table makes the descrambler blank A/V | Reset CAS table on the box — manual action | No |

P5 and P6 cannot be fixed reliably by a remote/software-only action; the tool
reports them but a physical/manual step is required.

## Repair over the online connection

`spidervip` connects to the receiver over SSH, reads the A/V pipeline state,
applies fixes in priority order, and re-checks picture/sound after each one.

### Prerequisites

- Receiver reachable on the LAN; know its IP.
- SSH/Telnet enabled on the box (default on most Linux/Enigma2 boxes).
- For the online backend: `pip install paramiko`.

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

1. Run `diagnose` to see the probable cause and its priority.
2. Run `repair`; it starts at the highest priority and re-verifies after each patch.
3. `picture OK, sound OK` means the fault is cleared.
4. Anything left under "manual attention" (signal / CAS) needs a physical step
   per the table above.

## Record for future use

- Save `diagnose`/`repair` output (use `--json`) per device to keep a history.
- When you adapt shell commands for a new model, add that `ReceiverProfile` to
  `spidervip/ssh_receiver.py` so it is ready next time.
