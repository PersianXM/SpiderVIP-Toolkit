# A/V freeze — manual recovery

Cause and automatic recovery: [`AUDIO_FREEZE_2026-11.md`](AUDIO_FREEZE_2026-11.md). Use this page only when the watchdog is not installed.

## Symptom

- Menu, remote and zapping work; no picture or sound on any channel.
- Telnet answers, so the kernel is alive.
- `cat /proc/msp/avplay00` returns `Resource temporarily unavailable`.
- `dmesg` repeats `call HI_DVB_DMX_GetTSBuffer failed` every 5 s.

## Steps

1. Take a read-only snapshot first: `python tools/freeze_state.py`
2. Hard reboot over Telnet: `/sbin/reboot -f`. If Telnet does not answer, cut the power.
3. Wait about 2 minutes for the picture.

## Did not work (2026-08-12)

- `killall bianbiang`: the player is stuck inside the kernel audio driver's lock.
- A soft `sync; reboot`.
- Changing channels.

## Never

- `rmmod g_service` or disabling `g_service`: it hangs the kernel and cuts the tuner/TS path.
