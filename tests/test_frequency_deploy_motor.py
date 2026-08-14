"""Frequency deploy must preserve Motor/USALS after servicelistreload."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from spidervip.channels.motor_profile import MotorProfile, SatMotorSetting, save_motor_profile


def test_resolve_motor_profile_prefers_channels_workspace(tmp_path: Path, monkeypatch):
    from spidervip.frequency import deploy

    ws = tmp_path / ".spidervip_channels"
    ws.mkdir()
    profile = MotorProfile(
        enabled=True,
        satellites=[
            SatMotorSetting(
                position="26.0E",
                satellite_name="26.0E Ku-band Badr",
                captured_window_b64="YQ==",
                captured_name_b64="Yg==",
            )
        ],
    )
    save_motor_profile(ws / "motor_profile.json", profile)
    monkeypatch.chdir(tmp_path)

    loaded, path = deploy.resolve_motor_profile()
    assert path == ws / "motor_profile.json"
    assert loaded is not None
    assert loaded.has_capture


def test_debug_mismatch_does_not_call_servicelistreload(monkeypatch):
    from spidervip.frequency import deploy

    calls = {"reload": 0}

    def _boom(*_a, **_k):
        calls["reload"] += 1
        raise AssertionError("webif_reload must not run during debug_mismatch")

    monkeypatch.setattr(deploy, "webif_reload", _boom)
    monkeypatch.setattr(
        deploy,
        "ftp_download",
        lambda *_a, **_k: (
            b'<?xml version="1.0"?><satellites>'
            b'<sat name="X" position="260">'
            b'<transponder frequency="11000000" symbol_rate="27500" '
            b'polarization="0" fec_inner="0" system="0" modulation="1"/>'
            b"</sat></satellites>"
        ),
    )
    monkeypatch.setattr(
        deploy,
        "_import_telnet",
        lambda: (None, lambda *_a, **_k: False),
    )

    xml = (
        b'<?xml version="1.0"?><satellites>'
        b'<sat name="X" position="260">'
        b'<transponder frequency="11000000" symbol_rate="27500" '
        b'polarization="0" fec_inner="0" system="0" modulation="1"/>'
        b'<transponder frequency="11100000" symbol_rate="27500" '
        b'polarization="0" fec_inner="0" system="0" modulation="1"/>'
        b"</sat></satellites>"
    )
    steps = deploy.debug_mismatch(xml, "127.0.0.1", "root", "root")
    assert calls["reload"] == 0
    assert any("بدون بازخوانی مجدد" in s for s in steps)


def test_send_to_receiver_motor_restore_order(monkeypatch):
    """backup → upload → reload → motor_restore; never reload after restore."""

    from spidervip.frequency import deploy

    events = []

    monkeypatch.setattr(
        deploy,
        "backup_live_prog_for_motor",
        lambda *a, **k: (
            "/data/gx/live_prog.bak_spidervip_freq",
            ["backup: ok"],
        ),
    )
    monkeypatch.setattr(
        deploy,
        "ftp_upload",
        lambda *a, **k: (events.append("upload"), ["FTP: uploaded"])[1],
    )
    monkeypatch.setattr(
        deploy,
        "verify_upload",
        lambda *a, **k: (True, "تأیید ✓"),
    )
    monkeypatch.setattr(
        deploy,
        "webif_reload",
        lambda *a, **k: (events.append("reload"), (True, ["WebIF ✓"]))[1],
    )
    monkeypatch.setattr(
        deploy,
        "confirm_reload",
        lambda *a, **k: (True, ["تأیید نهایی ✓"], {"total": 1, "per_sat": {}}),
    )

    def _restore(*a, **k):
        events.append("motor_restore")
        assert k.get("live_prog_backup") == "/data/gx/live_prog.bak_spidervip_freq"
        return ["motor_restore: method=pre_reload_backup windows=2"]

    monkeypatch.setattr(deploy, "restore_motor_after_reload", _restore)
    monkeypatch.setattr(
        deploy,
        "debug_mismatch",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debug on success")),
    )
    monkeypatch.setattr(
        deploy,
        "confirm_live_prog_commit",
        lambda *a, **k: (True, ["تأیید live_prog ✓"]),
    )

    xml = b'<?xml version="1.0"?><satellites></satellites>'
    result = deploy.send_to_receiver(xml, host="10.0.0.1", user="root", password="root")
    assert isinstance(result, dict)
    assert result["ok"] is True
    steps = result["steps"]

    # live DB upload + optional enigma_db_bak mirror both call ftp_upload.
    assert events[0] == "upload"
    assert "reload" in events
    assert events.index("reload") < events.index("motor_restore")
    assert events[-1] == "motor_restore"
    assert any(s.startswith("backup:") for s in steps)
    assert any(s.startswith("upload:") for s in steps)
    assert any(s.startswith("reload:") for s in steps)
    assert any(s.startswith("motor_restore:") for s in steps)
    assert any(s.startswith("done:") for s in steps)


def test_restore_motor_prefers_profile_then_backup(monkeypatch):
    from spidervip.frequency import deploy

    profile = MotorProfile(
        enabled=True,
        satellites=[
            SatMotorSetting(
                position="26.0E",
                satellite_name="26.0E Ku-band Badr",
                captured_window_b64="YQ==",
                captured_name_b64="Yg==",
            )
        ],
    )
    monkeypatch.setattr(
        deploy,
        "resolve_motor_profile",
        lambda *_a, **_k: (profile, Path("/tmp/motor_profile.json")),
    )

    fake_rx = MagicMock()
    fake_rx.apply_motor_profile.return_value = {
        "method": "profile_windows",
        "restored": 3,
    }
    fake_cls = MagicMock(return_value=fake_rx)
    monkeypatch.setattr(deploy, "_import_live_receiver", lambda: fake_cls)

    steps = deploy.restore_motor_after_reload(
        "10.0.0.1",
        "root",
        "root",
        live_prog_backup="/data/gx/live_prog.bak_spidervip_freq",
    )
    fake_rx.apply_motor_profile.assert_called_once()
    fake_rx.preserve_motor_from_backup.assert_not_called()
    assert any("method=profile_windows" in s for s in steps)
    assert any("بدون بازخوانی مجدد" in s for s in steps)


def test_restore_motor_falls_back_to_backup(monkeypatch):
    from spidervip.frequency import deploy

    monkeypatch.setattr(
        deploy,
        "resolve_motor_profile",
        lambda *_a, **_k: (None, None),
    )
    fake_rx = MagicMock()
    fake_rx.preserve_motor_from_backup.return_value = 4
    fake_cls = MagicMock(return_value=fake_rx)
    monkeypatch.setattr(deploy, "_import_live_receiver", lambda: fake_cls)

    steps = deploy.restore_motor_after_reload(
        "10.0.0.1",
        "root",
        "root",
        live_prog_backup="/data/gx/live_prog.bak_spidervip_freq",
    )
    fake_rx.preserve_motor_from_backup.assert_called_once_with(
        "/data/gx/live_prog.bak_spidervip_freq", min_size_ratio=0.95
    )
    assert any("method=pre_reload_backup windows=4" in s for s in steps)

def test_normalize_satellites_xml_bytes_strips_crlf():
    from spidervip.frequency import deploy

    raw = b"<?xml version=\"1.0\"?>\r\n<satellites>\r\n</satellites>\r\n"
    out = deploy.normalize_satellites_xml_bytes(raw)
    assert b"\r" not in out
    assert out.endswith(b"</satellites>\n")


def test_webif_reload_only_mode_zero():
    from spidervip.frequency import deploy

    assert deploy.RELOAD_MODES == (0,)


def test_send_to_receiver_fails_when_live_prog_unchanged(monkeypatch):
    """XML count match alone must not report success (Turksat-166 false positive)."""

    from spidervip.frequency import deploy

    monkeypatch.setattr(
        deploy,
        "backup_live_prog_for_motor",
        lambda *a, **k: ("/data/gx/live_prog.bak_spidervip_freq", ["backup: ok"]),
    )
    monkeypatch.setattr(deploy, "ftp_upload", lambda *a, **k: ["FTP: uploaded"])
    monkeypatch.setattr(deploy, "verify_upload", lambda *a, **k: (True, "تأیید ✓"))
    monkeypatch.setattr(deploy, "webif_reload", lambda *a, **k: (True, ["WebIF ✓"]))
    monkeypatch.setattr(
        deploy,
        "confirm_reload",
        lambda *a, **k: (True, ["تأیید نهایی ✓"], {"total": 1, "per_sat": {}}),
    )
    monkeypatch.setattr(
        deploy,
        "confirm_live_prog_commit",
        lambda *a, **k: (False, ["تأیید live_prog ✗: unchanged"]),
    )
    monkeypatch.setattr(deploy, "debug_mismatch", lambda *a, **k: ["debug"])
    monkeypatch.setattr(
        deploy, "restore_motor_after_reload", lambda *a, **k: ["motor_restore: skip"]
    )

    result = deploy.send_to_receiver(
        b"<?xml version=\"1.0\"?><satellites></satellites>",
        host="10.0.0.1",
        user="root",
        password="root",
    )
    assert result["ok"] is False
    assert result["confirm_ok"] is True
    assert result["live_prog_ok"] is False
    assert any("live_prog کامیت نشد" in s or s.startswith("fail:") for s in result["steps"])

