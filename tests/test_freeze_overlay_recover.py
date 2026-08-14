"""Recover-button contract tests (mocked — never touches the live box)."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def _load_freeze_overlay(tmp_state: Path):
    # Isolate STATE_PATH / canvas side effects before import executes.
    telnet_stub = types.ModuleType("telnet_run")
    telnet_stub.HOST = "192.168.100.102"
    telnet_stub.login = mock.Mock()
    telnet_stub.run = mock.Mock()
    sys.modules["telnet_run"] = telnet_stub

    path = TOOLS / "freeze_overlay.py"
    spec = importlib.util.spec_from_file_location("freeze_overlay_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    mod.STATE_PATH = str(tmp_state)
    mod.CANVAS = str(tmp_state.with_suffix(".canvas.tsx"))
    mod.SIDECAR = str(tmp_state.with_suffix(".canvas.data.json"))
    mod.patch_canvas = lambda snap: None
    return mod, telnet_stub


@pytest.fixture()
def fo(tmp_path):
    state = tmp_path / "freeze_overlay_state.json"
    mod, telnet = _load_freeze_overlay(state)
    yield mod, telnet


def test_native_win_widget_optional_contract():
    path = TOOLS / "freeze_overlay_win.py"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "run_ui" in text
    assert "_queue_recover" in text
    assert "recoverNote" in text
    assert "#3FA266" in text  # canvas category.green
    assert "#F1B467" in text  # canvas category.yellow
    assert "#FC6B83" in text  # canvas category.red
    assert "#3dd68c" not in text.lower()  # HTML palette must not leak in
    assert "Confirm reboot" in text
    assert "Recover (reboot)" in text
    assert "Last poll" in text
    assert "this PC" in text
    assert "webbrowser" not in text
    assert "ThreadingHTTPServer" not in text
    assert "paint_status(inner, kind, paint)" in text
    assert "paint_status(inner, kind)" not in text.replace("paint_status(inner, kind, paint)", "")


def test_freeze_overlay_win_imports():
    try:
        import tkinter as tk
    except Exception:
        pytest.skip("tkinter not available")
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except Exception:
        pytest.skip("no display")
    spec = importlib.util.spec_from_file_location("freeze_overlay_win_under_test", TOOLS / "freeze_overlay_win.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.run_ui)


def test_serve_ui_is_native_webview_not_http():
    body = (TOOLS / "freeze_overlay.py").read_text(encoding="utf-8")
    start = body.find("def serve_ui")
    assert start != -1
    nxt = body.find("\ndef ", start + 1)
    fn = body[start:nxt]
    assert "Tk fallback" in fn
    assert "except SystemExit as exc" in fn
    assert "freeze_overlay_web" in fn
    assert "run_ui" in fn
    assert "webbrowser" not in fn
    assert "ThreadingHTTPServer" not in fn
    assert "8791" not in fn
    assert "--ui-tk" in body
    assert "freeze_overlay_win" in fn


def test_webview_host_is_native_not_http():
    text = (TOOLS / "freeze_overlay_web.py").read_text(encoding="utf-8")
    assert "webview.create_window" in text
    assert "frameless=True" in text
    assert "on_top=True" in text
    assert "shadow=False" in text
    assert "http_server" in text
    assert "edgechromium" in text
    assert "evaluate_js" in text
    assert "self._window" in text
    assert "api.window =" not in text
    assert "js_api=api" in text
    assert "DWMWCP_ROUND" in text
    assert "WM_NCLBUTTONDOWN" in text
    assert "HTCAPTION" in text
    assert "def start_drag" in text
    assert "_content_height" in text
    assert "_CHROME_H" in text
    assert "_PROBE_ROW_H" in text
    assert "def fit_height" in text
    assert "SHELL_BG" in text
    assert "MAX_H" in text
    assert "_work_area_h" in text
    assert "easy_drag=False" in text
    assert "webbrowser" not in text
    assert "ThreadingHTTPServer" not in text
    assert "http://" not in text.lower()
    win = (TOOLS / "freeze_overlay_win.py").read_text(encoding="utf-8")
    assert "SpiderVIPFreezeOverlay.mutex" in text
    assert "SpiderVIPFreezeOverlay.mutex" in win


def test_recover_commands_are_onbox_force_reboot_and_zap():
    body = (TOOLS / "freeze_overlay.py").read_text(encoding="utf-8")
    assert "/sbin/reboot -f" in body
    assert "127.0.0.1:9095/web/zap" in body
    assert "ZAP_OK" in body
    assert "ZAP_DONE" not in body or "ZAP_OK" in body
    # Must not imply PC-side zap as primary path without on-box wget.
    assert "_onbox_zap_cmd" in body


def test_queue_recover_bumps_nonce_once(fo):
    mod, _telnet = fo
    mod._save_prev({"handledRecoverNonce": 3, "recoverNonce": 3})
    mod._queue_recover()
    prev = mod._load_prev()
    assert prev["recoverNonce"] == 4
    mod._queue_recover()
    prev = mod._load_prev()
    # Still handled+1 until consumed — no double-fire from repeated queue.
    assert prev["recoverNonce"] == 4


def test_recover_telnet_down_skips_reboot_and_reenables(fo):
    mod, telnet = fo
    telnet.login.side_effect = OSError("timed out")
    with mock.patch.object(mod, "probe", return_value=mod._fail_telnet("x", "recovering", "Backing up live_prog")):
        snap = mod.recover()
    assert snap["phase"] == "idle"
    assert "Telnet down" in snap["recoverNote"]
    assert snap["av"]["tone"] == "UNKNOWN"
    # Never sent reboot
    assert telnet.login.call_count >= 1


def test_recover_backup_fail_skips_reboot(fo):
    mod, telnet = fo
    sock = mock.Mock()
    telnet.login.return_value = sock
    telnet.run.return_value = "cp: error\n"
    with mock.patch.object(
        mod,
        "probe",
        return_value={
            "updatedAt": "t",
            "hostname": "clap4k",
            "host": mod.HOST,
            "phase": "recovering",
            "recoverNote": "Backing up live_prog",
            "telnet": mod._item("OK", "ok", False),
            "av": mod._item("FAIL", "bad", True, play="-", vid="-", aud="-"),
            "ui": mod._item("OK", "pid 1", False),
            "load": mod._item("OK", "1.0", False, value="1.0"),
            "vdec": mod._item("FAIL", "missing", True, frames=""),
        },
    ):
        snap = mod.recover()
    assert snap["phase"] == "idle"
    assert "Backup failed" in snap["recoverNote"]
    sock.sendall.assert_not_called()


def test_recover_reboot_send_fail_reported(fo):
    mod, telnet = fo
    sock = mock.Mock()
    sock.sendall.side_effect = BrokenPipeError("pipe")
    telnet.login.return_value = sock
    telnet.run.return_value = "BAK_OK\n"
    with mock.patch.object(
        mod,
        "probe",
        return_value={
            "updatedAt": "t",
            "hostname": "clap4k",
            "host": mod.HOST,
            "phase": "recovering",
            "recoverNote": "Backing up live_prog",
            "telnet": mod._item("OK", "ok", False),
            "av": mod._item("FAIL", "bad", True, play="-", vid="-", aud="-"),
            "ui": mod._item("OK", "pid 1", False),
            "load": mod._item("OK", "1.0", False, value="1.0"),
            "vdec": mod._item("FAIL", "missing", True, frames=""),
        },
    ):
        snap = mod.recover()
    assert "Reboot command failed" in snap["recoverNote"]
    assert snap["phase"] == "idle"
    sock.sendall.assert_called()
    assert b"/sbin/reboot -f" in sock.sendall.call_args[0][0]


def test_recover_zap_fail_note_after_boot(fo):
    mod, telnet = fo
    sock = mock.Mock()
    boot = mock.Mock()
    telnet.login.side_effect = [sock, boot]
    telnet.run.side_effect = [
        "BAK_OK\n",  # backup
        "12\n",  # uptime after reboot wait
        "ZAP_FAIL\n",  # zap
    ]
    probe_snap = {
        "updatedAt": "t",
        "hostname": "clap4k",
        "host": mod.HOST,
        "phase": "idle",
        "recoverNote": "",
        "telnet": mod._item("OK", "ok", False),
        "av": mod._item("OK", "PLAY", False, play="PLAY", vid="TRUE", aud="TRUE"),
        "ui": mod._item("OK", "pid 1", False),
        "load": mod._item("OK", "1.0", False, value="1.0"),
        "vdec": mod._item("OK", "ok", False, frames="1"),
    }

    def _probe(phase="idle", recover_note=""):
        out = dict(probe_snap)
        out["phase"] = phase
        out["recoverNote"] = recover_note
        return out

    with mock.patch.object(mod, "probe", side_effect=_probe), mock.patch.object(mod.time, "sleep", return_value=None):
        snap = mod.recover()
    assert snap["phase"] == "idle"
    assert "zap failed" in snap["recoverNote"].lower()
    zap_cmd = telnet.run.call_args_list[-1][0][1]
    assert "127.0.0.1:9095" in zap_cmd
    assert "ZAP_OK" in zap_cmd


def test_html_confirm_then_js_api_recover():
    html = (TOOLS / "freeze_overlay.html").read_text(encoding="utf-8")
    assert "if (!confirm)" in html
    assert "bridge.recover" in html
    assert 'fetch("/api/recover"' not in html
    assert "CONFIRM_ARM_SEC" in html
    assert "CONFIRM_HOLD_SEC" in html
    assert "#3FA266" in html
    assert "#F1B467" in html
    assert "#FC6B83" in html
    assert "#181818" in html
    assert "#262626" in html
    assert "#3dd68c" not in html.lower()
    assert "linear-gradient" not in html
    assert "backdrop-filter" not in html
    assert "pywebview-drag-region" not in html
    assert "start_drag" in html
    assert "border-radius: 0" in html
    assert "contentHeight" in html or "requestFit" in html
    assert "min-height: 0" in html or "height: auto" in html
    assert "isDragExempt" in html
    web = (TOOLS / "freeze_overlay_web.py").read_text(encoding="utf-8")
    assert "DWMWCP_ROUND" in web
    assert "DwmSetWindowAttribute" in web
    assert "WM_NCLBUTTONDOWN" in web
    assert "applySnapshot" in html
    assert "Video window" in html
    assert "Audio decoder" in html
    assert 'id="appVersion"' in html


def test_poll_once_consumes_nonce(fo):
    mod, telnet = fo
    telnet.login.side_effect = OSError("down")
    mod._save_prev({"handledRecoverNonce": 0, "recoverNonce": 1})
    with mock.patch.object(mod, "probe", return_value=mod._fail_telnet("x", "recovering", "Backing up live_prog")):
        snap = mod._poll_once()
    prev = mod._load_prev()
    assert prev["handledRecoverNonce"] == 1
    assert snap["recoverNote"]
    assert prev.get("snapshot", {}).get("recoverNote") == snap["recoverNote"]


def _load_win():
    path = TOOLS / "freeze_overlay_win.py"
    spec = importlib.util.spec_from_file_location("freeze_overlay_win_logic", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def winmod():
    return _load_win()


def test_confirm_arming_gate_blocks_double_click(winmod):
    assert 0.4 <= winmod.CONFIRM_ARM_SEC <= 0.6
    t0 = 100.0
    assert winmod.confirm_ready(None, t0) is False
    assert winmod.confirm_ready(t0, t0) is False
    assert winmod.confirm_ready(t0, t0 + 0.39) is False
    assert winmod.confirm_ready(t0, t0 + winmod.CONFIRM_ARM_SEC) is True
    assert winmod.confirm_ready(t0, t0 + 0.70) is True


def test_confirm_expires_and_esc_cancels_not_close(winmod):
    assert winmod.CONFIRM_HOLD_SEC >= 4.0
    t0 = 10.0
    assert winmod.confirm_expired(t0, t0 + 4.9) is False
    assert winmod.confirm_expired(t0, t0 + 5.0) is True
    assert winmod.escape_should_close(True) is False
    assert winmod.escape_should_close(False) is True


def test_show_recover_matches_canvas_gating(winmod):
    assert winmod.show_recover(freeze=False, confirm=False, recovering=False) is False
    assert winmod.show_recover(freeze=True, confirm=False, recovering=False) is True
    assert winmod.show_recover(freeze=False, confirm=True, recovering=False) is True
    assert winmod.show_recover(freeze=False, confirm=False, recovering=True) is True


def test_play_ok_is_not_freeze(winmod):
    snap = {
        "av": {"tone": "OK", "blink": False, "play": "PLAY"},
        "stat": {"tone": "OK", "blink": False},
        "vpss": {"tone": "OK", "blink": False},
        "vdec": {"tone": "OK", "blink": False},
        "win": {"tone": "OK", "blink": False},
        "adec": {"tone": "OK", "blink": False},
        "sync": {"tone": "OK", "blink": False},
    }
    assert winmod.is_freeze_snap(snap) is False
    assert winmod.is_healthy_snap(snap) is True


def test_msp_timeout_is_not_freeze(winmod):
    snap = {
        "av": {"tone": "UNKNOWN", "blink": False, "play": "-"},
        "stat": {"tone": "UNKNOWN", "blink": False},
        "vpss": {"tone": "UNKNOWN", "blink": False},
        "vdec": {"tone": "UNKNOWN", "blink": False},
        "win": {"tone": "UNKNOWN", "blink": False},
        "adec": {"tone": "UNKNOWN", "blink": False},
        "sync": {"tone": "UNKNOWN", "blink": False},
    }
    assert winmod.is_freeze_snap(snap) is False


def test_av_fail_is_freeze(winmod):
    snap = {
        "av": {"tone": "FAIL", "blink": True, "play": "-"},
        "stat": {"tone": "OK", "blink": False},
        "vpss": {"tone": "OK", "blink": False},
        "vdec": {"tone": "FAIL", "blink": True},
        "win": {"tone": "OK", "blink": False},
        "adec": {"tone": "OK", "blink": False},
        "sync": {"tone": "OK", "blink": False},
    }
    assert winmod.is_freeze_snap(snap) is True
    assert winmod.is_healthy_snap(snap) is False


def test_stale_when_updated_at_older_than_two_polls(winmod):
    from datetime import datetime

    now = datetime(2026, 8, 14, 17, 0, 0)
    fresh = "2026-08-14 16:59:40"
    stale = "2026-08-14 16:58:00"
    assert winmod.is_stale(fresh, poll_sec=12, now=now) is False
    assert winmod.is_stale(stale, poll_sec=12, now=now) is True
    assert winmod.is_stale("--:--", poll_sec=12, now=now) is False
    assert winmod.is_stale("", poll_sec=12, now=now) is False


def test_clock_digits_and_rows_map_probe_fields(winmod):
    assert winmod.clock_digits("2026-08-14 17:09:25") == ("17", "09")
    assert winmod.clock_digits("") == ("--", "--")
    keys = [k for k, _ in winmod.ROWS]
    labels = [lab for _, lab in winmod.ROWS]
    assert keys[0] == "av"
    assert keys[1] == "stat"
    assert keys[2] == "vpss"
    assert "stall" in keys
    assert keys[-2:] == ["telnet", "ui"]
    assert labels[0] == "Audio / Video"
    assert "MSP flow" in labels
    assert winmod.FREEZE_KEYS == ("av", "stat", "vpss", "vdec", "win", "adec", "sync")
    assert winmod.DIGIT_CELL == 7.0
    assert winmod.DIGIT_GAP == 2.2
    assert winmod.DIGIT_PAD == 8.0
    assert winmod.CORNER_R == 36
    assert winmod.TILE_R == 14
    assert winmod.PROBES_R == 18
    assert winmod.HIT >= 44


def test_canvas_palette_matches_host_theme_tokens(winmod):
    assert winmod.OK == "#3FA266"
    assert winmod.WARN == "#F1B467"
    assert winmod.FAIL == "#FC6B83"
    assert winmod.BG_EDITOR == "#181818"
    assert winmod.WIN_ALPHA == 1.0
    assert winmod.SHELL_PAD == 22
    assert winmod.SHELL_BG == winmod._hex8_on("#181818", "#E4E4E411")
    assert winmod.TILE_BG == winmod._hex8_on("#181818", "#E4E4E41E")
    assert winmod.TEXT == winmod._hex8_on(winmod.SHELL_BG, "#E4E4E4EB")
    assert winmod.TEXT_2 == winmod._hex8_on(winmod.SHELL_BG, "#E4E4E48D")
    assert winmod.TEXT_3 == winmod._hex8_on(winmod.SHELL_BG, "#E4E4E45E")
    assert winmod.TILE_TEXT_2 == winmod._hex8_on(winmod.TILE_BG, "#E4E4E48D")
    assert winmod.TILE_TEXT_3 == winmod._hex8_on(winmod.TILE_BG, "#E4E4E45E")
    assert winmod.DIGIT_ON == winmod._hex8_on(winmod.TILE_BG, "#E4E4E4EB")
    assert winmod.DIGIT_OFF == winmod._hex8_on(winmod.TILE_BG, "#E4E4E40A")


def test_recover_titles_and_note_colors(winmod):
    assert winmod.recover_title(False, False) == "Recover (reboot)"
    assert winmod.recover_title(True, False) == "Confirm reboot"
    assert winmod.recover_title(False, True) == "Recovering"
    assert winmod.note_color("Backup failed - reboot skipped", False) == winmod.FAIL
    assert winmod.note_color("Telnet down - cannot recover", False) == winmod.FAIL
    assert winmod.note_color("Backing up live_prog", True) == winmod.WARN
    assert winmod.note_color("Zapped Iran International HD - watching A/V", False) == winmod.OK
    assert "Confirm reboot" in winmod.NOTE_CONFIRM


def test_write_snapshot_preserves_queued_recover_nonce(fo):
    mod, _telnet = fo
    mod._save_prev({"recoverNonce": 9, "handledRecoverNonce": 8, "frames": 1})
    snap = {"phase": "idle", "recoverNote": ""}
    mod._write_snapshot(snap, frames=2)
    prev = mod._load_prev()
    assert prev["recoverNonce"] == 9
    assert prev["handledRecoverNonce"] == 8
    assert prev["frames"] == 2
    assert prev["snapshot"] == snap


def test_probe_does_not_drop_nonce_queued_during_poll(fo):
    mod, telnet = fo
    sock = mock.Mock()
    telnet.login.return_value = sock

    def run(_s, cmd, _idx, timeout=8):
        if "hostname" in cmd:
            mod._queue_recover()
            return "clap4k"
        if "loadavg" in cmd:
            return "0.50 0.40 0.30"
        if "uptime" in cmd:
            return "100.12 0.00"
        if "pidof" in cmd:
            return "1470"
        if "live_prog" in cmd:
            return "85548 /data/gx/live_prog"
        if "sv_avplay" in cmd or "CurStatus" in cmd:
            return "MSP_TIMEOUT"
        if "sv_stat" in cmd or "FRAMEDECED" in cmd:
            return "MSP_TIMEOUT"
        if "sv_vpss" in cmd or "ProcessHZ" in cmd:
            return "MSP_TIMEOUT"
        if "sv_vdec" in cmd or "NO_VDEC" in cmd:
            return "MSP_TIMEOUT"
        if "sv_win" in cmd or "NO_WIN" in cmd:
            return "MSP_TIMEOUT"
        if "sv_adec" in cmd or "NO_ADEC" in cmd:
            return "MSP_TIMEOUT"
        if "sv_sync" in cmd or "NO_SYNC" in cmd:
            return "MSP_TIMEOUT"
        return ""

    telnet.run.side_effect = run
    snap = mod.probe()
    prev = mod._load_prev()
    assert prev["recoverNonce"] == 1
    assert snap["av"]["tone"] == "UNKNOWN"
    assert snap["av"]["blink"] is False
    assert snap["vdec"]["tone"] == "UNKNOWN"
    assert snap["win"]["tone"] == "UNKNOWN"
    assert snap["adec"]["tone"] == "UNKNOWN"
    assert snap["telnet"]["tone"] == "OK"
    assert snap["ui"]["tone"] == "OK"
    assert mod.snap_is_freeze(snap) is False


def test_sensor_keys_align_between_probe_and_widget(fo, winmod):
    mod, _telnet = fo
    assert tuple(k for k, _ in winmod.ROWS) == mod.SENSOR_KEYS
    assert winmod.FREEZE_KEYS == mod.FREEZE_KEYS


def test_vidpid_null_alone_is_warn_not_freeze(fo):
    mod, _telnet = fo
    tone, blink, detail = mod._av_tone_from_fields(
        {"timeout": False, "play": "PLAY", "vid": "TRUE", "aud": "TRUE", "vidpid": "0x1fff"},
        True,
    )
    assert tone == "WARN"
    assert blink is False
    assert "0x1fff" in detail
    snap = {
        "av": mod._item(tone, detail, blink),
        "stat": mod._item("OK", "dec 1", False),
        "vpss": mod._item("OK", "ProcessHZ 50/50", False),
        "vdec": mod._item("OK", "ok", False),
        "win": mod._item("OK", "ok", False),
        "adec": mod._item("OK", "ok", False),
        "sync": mod._item("OK", "ok", False),
    }
    assert mod.snap_is_freeze(snap) is False


def test_stat_and_vpss_parsers(fo):
    mod, _telnet = fo
    st = mod._stat_item(mod._parse_stat("STREAMIN : 100\nFRAMEDECED : 200\nLOCKED : 1\n"), None)
    assert st["tone"] == "OK"
    stuck = mod._stat_item(
        mod._parse_stat("STREAMIN : 100\nFRAMEDECED : 200\n"),
        {"framedeced": 200},
    )
    assert stuck["tone"] == "WARN"
    vp = mod._vpss_item(mod._parse_vpss("ProcessHZ(Try/OK)    :197/51\nAcquireHZ        :50\n"))
    assert vp["tone"] == "OK"
    dead = mod._vpss_item(mod._parse_vpss("ProcessHZ(Try/OK) :0/0\nAcquireHZ :0\n"))
    assert dead["tone"] == "FAIL"


def test_launcher_is_native_ui_not_browser():
    bat = (ROOT / "RUN_FREEZE_OVERLAY.bat").read_text(encoding="utf-8")
    assert "freeze_overlay.py %UI%" in bat
    assert "--ui-tk" in bat
    assert "import webview" in bat
    assert "PYTHONPATH" in bat
    assert "Python not found" in bat
    assert "freeze_overlay.html" not in bat
    assert "http://" not in bat.lower()
    assert "already running" in bat.lower()
    assert "tkinter" in bat
    assert "WebView2" in bat
    assert "pywebview" in bat


def test_parse_av_msp_timeout_unknown_contract(fo):
    mod, _telnet = fo
    parsed = mod._parse_av("foo\nMSP_TIMEOUT\n")
    assert parsed["timeout"] is True
    assert parsed["play"] == ""


_WIN_DUMP = """
WIN_OK
Enable             :True                |Type/PixFmt       :2D        /NV21
State              :Run                 |Rotation          :Rotation_00
Type               :Display             |W/H(Aspect W:H)   : 720/ 576(   4:   3)
AspectRatioConvert :Full                |FrameRate         :50.000
In  (X/Y/W/H)      :   0/   0/   0/   0 |FrameIndex        :0xdddb
[1]+  Done                    ( if test -e /proc/msp/win0100; then head -c 4096 /proc/msp/win0100; else echo NO_WIN; fi) > $W 2>&1
"""

_ADEC_DUMP = """
ADEC_OK
WorkState                              :start
DecoderName                            :mp2
SampleRate                             :48000
Channels                               :2
FrameNum(Total/Error)                  :94705/0
[1]+  Done                    ( if test -e /proc/msp/adec00; then head -c 4096 /proc/msp/adec00; else echo NO_ADEC; fi) > $A 2>&1
"""


def test_parse_win_reads_live_fields(fo):
    mod, _telnet = fo
    parsed = mod._parse_win(_WIN_DUMP)
    assert parsed["timeout"] is False
    assert parsed["missing"] is False
    assert parsed["enable"] == "True"
    assert parsed["state"] == "Run"
    assert parsed["wh"] == "720x576"
    assert parsed["fps"] == "50.000"
    assert parsed["idx"] == "0xdddb"
    item = mod._win_item(parsed)
    assert item["tone"] == "OK"
    assert "720x576" in item["detail"]
    assert "50fps" in item["detail"]
    assert "True" in item["detail"]
    job = mod._parse_win("[1]+  Done echo NO_WIN\nWIN_OK\nEnable :True\nState :Run\n")
    assert job["missing"] is False


def test_parse_win_missing_and_timeout(fo):
    mod, _telnet = fo
    miss = mod._win_item(mod._parse_win("NO_WIN\n"))
    assert miss["tone"] == "FAIL"
    assert "missing" in miss["detail"]
    timed = mod._win_item(mod._parse_win("MSP_TIMEOUT\n"))
    assert timed["tone"] == "UNKNOWN"
    off = mod._win_item(mod._parse_win("WIN_OK\nEnable :False\nState :Stop\n"))
    assert off["tone"] == "FAIL"


def test_parse_adec_reads_live_fields(fo):
    mod, _telnet = fo
    parsed = mod._parse_adec(_ADEC_DUMP)
    assert parsed["timeout"] is False
    assert parsed["missing"] is False
    assert parsed["work"] == "start"
    assert parsed["codec"] == "mp2"
    assert parsed["rate"] == "48000"
    assert parsed["ch"] == "2"
    assert parsed["frames"] == "94705/0"
    item = mod._adec_item(parsed)
    assert item["tone"] == "OK"
    assert "mp2" in item["detail"]
    assert "48kHz" in item["detail"]
    assert "2ch" in item["detail"]
    assert "94705/0" in item["detail"]
    job = mod._parse_adec("[1]+  Done echo NO_ADEC\nADEC_OK\nWorkState :start\n")
    assert job["missing"] is False


def test_parse_adec_missing_and_stop(fo):
    mod, _telnet = fo
    miss = mod._adec_item(mod._parse_adec("NO_ADEC\n"))
    assert miss["tone"] == "FAIL"
    timed = mod._adec_item(mod._parse_adec("MSP_TIMEOUT\n"))
    assert timed["tone"] == "UNKNOWN"
    stopped = mod._adec_item(mod._parse_adec("ADEC_OK\nWorkState :stop\nDecoderName :mp2\n"))
    assert stopped["tone"] == "FAIL"


def test_win_adec_hold_last_ok_on_msp_timeout(fo):
    mod, telnet = fo
    telnet.login.return_value = mock.Mock()
    ok_win = mod._win_item(
        mod._parse_win("WIN_OK\nEnable :True\nState :Run\nW/H(Aspect W:H)   : 720/ 576\n")
    )
    ok_adec = mod._adec_item(
        mod._parse_adec("ADEC_OK\nWorkState :start\nDecoderName :mp2\nSampleRate :48000\n")
    )
    mod._save_prev({"snapshot": {"win": ok_win, "adec": ok_adec}})

    def run(_s, cmd, _idx, timeout=8):
        if "hostname" in cmd:
            return "clap4k"
        if "pidof" in cmd:
            return "1470"
        if "sv_avplay" in cmd or "CurStatus" in cmd:
            return "CurStatus : PLAY\nVid Enable : TRUE\nAud Enable : TRUE\nVidPid : 0x3ad"
        if "sv_stat" in cmd:
            return "STREAMIN : 10\nFRAMEDECED : 20\nLOCKED : 1\n"
        if "sv_vpss" in cmd:
            return "ProcessHZ : 50/50\n"
        if "sv_vdec" in cmd or "NO_VDEC" in cmd:
            return "VDEC_OK\nState :RUN\n"
        if "sv_win" in cmd or "NO_WIN" in cmd:
            return "MSP_TIMEOUT"
        if "sv_adec" in cmd or "NO_ADEC" in cmd:
            return "MSP_TIMEOUT"
        if "sv_sync" in cmd:
            return "CrtStatus :PCR\n"
        return ""

    telnet.run.side_effect = run
    snap = mod.probe()
    assert snap["win"]["tone"] == "OK"
    assert "720x576" in snap["win"]["detail"]
    assert snap["adec"]["tone"] == "OK"
    assert "mp2" in snap["adec"]["detail"]


def test_win_adec_missing_still_fails_after_ok(fo):
    mod, telnet = fo
    telnet.login.return_value = mock.Mock()
    ok_win = mod._win_item(mod._parse_win("WIN_OK\nEnable :True\nState :Run\n"))
    ok_adec = mod._adec_item(mod._parse_adec("ADEC_OK\nWorkState :start\n"))
    mod._save_prev({"snapshot": {"win": ok_win, "adec": ok_adec}})

    def run(_s, cmd, _idx, timeout=8):
        if "hostname" in cmd:
            return "clap4k"
        if "pidof" in cmd:
            return "1470"
        if "sv_avplay" in cmd:
            return "CurStatus : PLAY\nVid Enable : TRUE\nAud Enable : TRUE\nVidPid : 0x3ad"
        if "sv_stat" in cmd:
            return "STREAMIN : 10\nFRAMEDECED : 20\n"
        if "sv_vpss" in cmd:
            return "ProcessHZ : 50/50\n"
        if "sv_vdec" in cmd:
            return "VDEC_OK\nState :RUN\n"
        if "sv_win" in cmd:
            return "NO_WIN"
        if "sv_adec" in cmd:
            return "NO_ADEC"
        if "sv_sync" in cmd:
            return "CrtStatus :PCR\n"
        return ""

    telnet.run.side_effect = run
    snap = mod.probe()
    assert snap["win"]["tone"] == "FAIL"
    assert snap["adec"]["tone"] == "FAIL"


def test_recover_fail_notes_are_english(fo):
    mod, telnet = fo
    telnet.login.side_effect = OSError("timed out")
    with mock.patch.object(mod, "probe", return_value=mod._fail_telnet("x", "recovering", "Backing up live_prog")):
        snap = mod.recover()
    assert snap["recoverNote"]
    assert snap["recoverNote"].isascii()
    assert "Telnet down" in snap["recoverNote"]
