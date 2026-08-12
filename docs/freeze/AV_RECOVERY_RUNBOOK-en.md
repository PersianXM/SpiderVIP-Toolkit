# A/V freeze recovery runbook — live validation 2026-08-12

See the full Persian runbook (primary): [`AV_RECOVERY_RUNBOOK_2026-08-12.md`](AV_RECOVERY_RUNBOOK_2026-08-12.md).

## Quick recovery (validated)

Symptoms: menu and zapping work; all channels have no picture/sound; Telnet alive.

1. Light probe: `avplay=STOP` or no `/proc/msp/vdec00` while `bianbiang` runs.
2. Optional: `python tools/freeze_capture.py` (may hang if MSP wedged).
3. `cp /data/gx/live_prog /data/live_prog_usals_ok.bak && sync`
4. Deploy patches once: `python tools/av_recovery_run.py --deploy-only`
5. **`/sbin/reboot -f`** (plain `reboot` from Telnet did not reboot this box).
6. Wait ~90s; zap test channel; wait 50s for USALS motor.
7. Confirm: `CurStatus:PLAY`, `vdec00` exists, VPSS ~50Hz.

Test channel **Iran International HD** (Badr 26.0E):

```
1:0:2:82:2:1:1042FE9:0:0:0:
```

Automated: `python tools/av_recovery_run.py`

## Do we have a repeatable fix?

**Yes** for MSP play-path wedge (P1/P11) with live Telnet.

**No** single fix for: full kernel hang, weak signal, scrambled services, or `rmmod g_service`.

## Patch status

- **Shipped in repo:** `patches/usr/bin/bianbiang.sh`, `patches/etc/sysctl.conf`, `tools/deploy_freeze_watch.py`
- **Proposed next:** optional auto-reboot in `freeze_watch.conf`, non-blocking `freeze_dump.sh`, motor restore from `motor_profile.json`
