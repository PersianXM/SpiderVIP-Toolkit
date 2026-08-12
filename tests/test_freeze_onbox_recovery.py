"""Guards for on-box A/V freeze auto-recovery scripts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def _read(name: str) -> str:
    return (TOOLS / name).read_text(encoding="utf-8")


def test_recovery_uses_force_reboot_not_plain_reboot():
    body = _read("av_recovery.sh")
    assert "/sbin/reboot -f" in body
    assert not any(line.strip().startswith("rmmod") for line in body.splitlines())
    assert not any("killall bianbiang" in line and not line.strip().startswith("#") for line in body.splitlines())


def test_watch_calls_recovery_after_hold():
    watch = _read("freeze_watch.sh")
    assert "av_recovery.sh" in watch
    assert "freeze_recovery_allowed" in watch
    assert "freeze_is_av_frozen" in watch


def test_dump_uses_timed_msp_reads_and_budget():
    dump = _read("freeze_dump.sh")
    assert "freeze_timed_grab" in dump
    assert "DUMP_MAX_SEC" in dump
    assert "dump_over_budget" in dump


def test_lib_does_not_wait_on_dstate_timeout():
    lib = _read("freeze_lib.sh")
    assert "return 124" in lib
    assert "kill -0" in lib
    assert "BOOT_GRACE_SEC" in lib
    assert "MAX_RECOVERIES" in lib
    assert "DISABLE_AUTO_RECOVERY" in lib


def test_motor_restore_only_if_live_prog_missing():
    body = _read("motor_boot_restore.sh")
    assert 'if [ -s "$LIVE" ]' in body
    assert "live_prog.last_good" in body


def test_deploy_defaults_auto_recovery_on_and_skips_dbgbar():
    deploy = _read("deploy_freeze_watch.py")
    assert "AUTO_RECOVERY=%(auto)s" in deploy
    assert "av_recovery.sh" in deploy
    assert "motor_boot_restore.sh" in deploy
    assert "HOLD_SEC=120" in deploy
    assert "dbgbar" not in deploy.lower()
    conf_default = deploy.split("CONF_TEMPLATE")[1]
    assert "--no-auto-recovery" in deploy


def test_autostart_restores_motor_then_starts_watch():
    deploy = _read("deploy_freeze_watch.py")
    assert "motor_boot_restore.sh" in deploy
    assert "freeze_watch.sh" in deploy
    # motor restore must run before the watcher loop
    auto = deploy.split("AUTOSTART_BODY")[1].split("USER_SCRIPT_BODY")[0]
    assert auto.find("motor_boot_restore.sh") < auto.find("freeze_watch.sh")
