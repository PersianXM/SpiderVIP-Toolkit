# SpiderVIP-Firmware-Patch

Toolkit to diagnose and **remotely repair the "no picture / no sound" (audio-video
freeze)** fault on SpiderVIP-class satellite receivers — the case where dish
control, channel zapping, power on/off and the settings menu all work, but every
channel is black and silent.

It connects to the receiver over the network, works through a **prioritized list
of probable causes**, applies fixes one at a time, and re-checks picture/sound
after each step.

## What it does

- **Diagnose** – reads the receiver's A/V pipeline state and lists the probable
  causes, highest priority first.
- **Repair** – applies the matching remote fixes in priority order and verifies
  that picture and sound come back.
- **Simulate** – a built-in receiver simulator reproduces the symptom so the whole
  flow can be run and tested without hardware.

## Install

```bash
pip install -e ".[online]"   # 'online' adds paramiko for the SSH backend
```

The core (diagnostics, patch engine, simulator, CLI) has no runtime dependencies;
only the online SSH backend needs `paramiko`.

## Usage

```bash
# Against a real receiver on the LAN (online connection)
spidervip diagnose --host 192.168.1.50 --user root --password ****** --profile enigma2
spidervip repair   --host 192.168.1.50 --user root --password ******

# Against the simulator (no hardware needed)
spidervip faults
spidervip diagnose --simulate --fault player-crash
spidervip repair   --simulate --fault demux-stuck --fault audio-muted --json
```

`repair --dry-run` prints the plan without touching the receiver.

## How it decides what to fix

Because the on-screen **menu renders fine**, the SoC/OSD/display path are known
good, so the fault sits between the tuner and the A/V decoders (or in the
decode/output stage). Causes are ranked by likelihood-given-symptoms and how
cheaply they can be fixed remotely — full table in the docs below.

## Documentation

- Persian troubleshooting guide: [`docs/troubleshooting-fa.md`](docs/troubleshooting-fa.md)
- English troubleshooting guide: [`docs/troubleshooting-en.md`](docs/troubleshooting-en.md)

## Layout

```
spidervip/
  diagnostics.py   # ranked fault checks
  patches.py       # remote fixes, one per fault
  repair.py        # orchestrator: diagnose -> fix by priority -> re-verify
  receiver.py      # abstract receiver interface
  simulator.py     # fault-injectable simulator (tests & demos)
  ssh_receiver.py  # online SSH backend + per-firmware command profiles
  cli.py           # `spidervip` command
tests/             # pytest suite
```

## Development

```bash
pip install -e ".[online,dev]"
pytest -q
```
