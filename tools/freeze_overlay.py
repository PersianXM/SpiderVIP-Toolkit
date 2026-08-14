#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live freeze-overlay probe for the clap4k lab box.

Read-only polls by default. Recovery (backup live_prog, reboot -f, on-box zap)
runs only when --recover is passed, the UI Recover button queues a nonce, or
the canvas Recover control bumps recoverNonce. Never auto-recovers.

Does not deploy freeze_watch.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import telnet_run  # noqa: E402

HOST = telnet_run.HOST
ZAP_REF = "1:0:2:82:2:1:1042FE9:0:0:0:"
LIVE_PROG_BAK = "/data/live_prog_usals_ok.bak"
POLL_SEC = 12
MSP_SEC = 3
# Widget STALE if last successful poll is older than two intervals plus probe budget.
STALE_GRACE_SEC = 20
# Display order = diagnostic importance (path flow first, context last).
SENSOR_ROWS = (
    ("av", "Audio / Video"),
    ("stat", "MSP flow"),
    ("vpss", "VPSS"),
    ("vdec", "VDEC"),
    ("win", "Video window"),
    ("adec", "Audio decoder"),
    ("sync", "AV sync"),
    ("demux", "Demux"),
    ("frontend", "Frontend"),
    ("hdmi", "HDMI"),
    ("stall", "MSP stall"),
    ("telnet", "Telnet"),
    ("ui", "UI"),
)
SENSOR_KEYS = tuple(k for k, _ in SENSOR_ROWS)
# FREEZE pill: real A/V path. demux/frontend/hdmi/telnet/ui/stall are context.
FREEZE_KEYS = ("av", "stat", "vpss", "vdec", "win", "adec", "sync")

CANVAS = os.path.join(
    os.path.expanduser("~"),
    ".cursor",
    "projects",
    "g-Spider-Receiver-SpiderVIP-Toolkit",
    "canvases",
    "freeze-status.canvas.tsx",
)
SIDECAR = CANVAS.replace(".canvas.tsx", ".canvas.data.json")
STATE_PATH = os.path.join(HERE, "..", ".spidervip_channels", "freeze_overlay_state.json")

_SNAP_RE = re.compile(
    r"// SNAPSHOT_BEGIN\nconst SNAPSHOT: Snapshot = \{.*?\n\}; // SNAPSHOT_END",
    re.S,
)

# Timed MSP grab: never wait on D-state /proc/msp (busybox timeout hangs).
_AV_CMD = (
    "AV=/tmp/sv_avplay; : > $AV; "
    "head -c 4096 /proc/msp/avplay00 > $AV 2>&1 & HP=$!; "
    "i=0; while [ $i -lt %d ]; do kill -0 $HP 2>/dev/null || break; sleep 1; i=$((i+1)); done; "
    "if kill -0 $HP 2>/dev/null; then kill -9 $HP 2>/dev/null; echo MSP_TIMEOUT; "
    "else "
    "G=$(grep -E 'CurStatus|Vid Enable|VidPid|Aud Enable' $AV | head -8); "
    "if [ -n \"$G\" ]; then echo \"$G\"; else echo AVPLAY_EMPTY; wc -c $AV; fi; "
    "fi"
) % MSP_SEC

_VDEC_CMD = (
    "V=/tmp/sv_vdec; : > $V; "
    "(if test -e /proc/msp/vdec00; then head -c 4096 /proc/msp/vdec00; else echo NO_VDEC; fi) > $V 2>&1 & HP=$!; "
    "i=0; while [ $i -lt %d ]; do kill -0 $HP 2>/dev/null || break; sleep 1; i=$((i+1)); done; "
    "if kill -0 $HP 2>/dev/null; then kill -9 $HP 2>/dev/null; echo MSP_TIMEOUT; "
    "else "
    "if grep -q '^NO_VDEC$' $V 2>/dev/null; then echo NO_VDEC; "
    "else echo VDEC_OK; "
    "G=$(grep -E 'State|state |BitRate|ErrFrame|ErrCover|FrameRate|Width|Height' $V | head -12); "
    "if [ -n \"$G\" ]; then echo \"$G\"; else echo VDEC_EMPTY; fi; "
    "fi; fi"
) % MSP_SEC

_WIN_CMD = (
    "W=/tmp/sv_win; : > $W; "
    "(if test -e /proc/msp/win0100; then head -c 4096 /proc/msp/win0100; else echo NO_WIN; fi) > $W 2>&1 & HP=$!; "
    "i=0; while [ $i -lt %d ]; do kill -0 $HP 2>/dev/null || break; sleep 1; i=$((i+1)); done; "
    "if kill -0 $HP 2>/dev/null; then kill -9 $HP 2>/dev/null; echo MSP_TIMEOUT; "
    "else "
    "if grep -q '^NO_WIN$' $W 2>/dev/null; then echo NO_WIN; "
    "else echo WIN_OK; "
    "G=$(grep -E 'Enable |State +|W/H\\(Aspect|FrameRate |FrameIndex' $W | head -10); "
    "if [ -n \"$G\" ]; then echo \"$G\"; else echo WIN_EMPTY; wc -c $W; fi; "
    "fi; fi"
) % MSP_SEC

_ADEC_CMD = (
    "A=/tmp/sv_adec; : > $A; "
    "(if test -e /proc/msp/adec00; then head -c 4096 /proc/msp/adec00; else echo NO_ADEC; fi) > $A 2>&1 & HP=$!; "
    "i=0; while [ $i -lt %d ]; do kill -0 $HP 2>/dev/null || break; sleep 1; i=$((i+1)); done; "
    "if kill -0 $HP 2>/dev/null; then kill -9 $HP 2>/dev/null; echo MSP_TIMEOUT; "
    "else "
    "if grep -q '^NO_ADEC$' $A 2>/dev/null; then echo NO_ADEC; "
    "else echo ADEC_OK; "
    "G=$(grep -E 'WorkState|DecoderName|SampleRate|Channels |FrameNum' $A | head -10); "
    "if [ -n \"$G\" ]; then echo \"$G\"; else echo ADEC_EMPTY; wc -c $A; fi; "
    "fi; fi"
) % MSP_SEC

_STAT_CMD = (
    "S=/tmp/sv_stat; : > $S; "
    "(if test -e /proc/msp/stat; then grep -E 'STREAMIN|FRAMEDECED|LOCKED|VSTOP' /proc/msp/stat; "
    "else echo NO_STAT; fi) > $S 2>&1 & HP=$!; "
    "i=0; while [ $i -lt %d ]; do kill -0 $HP 2>/dev/null || break; sleep 1; i=$((i+1)); done; "
    "if kill -0 $HP 2>/dev/null; then kill -9 $HP 2>/dev/null; echo MSP_TIMEOUT; else cat $S; fi"
) % MSP_SEC

_VPSS_CMD = (
    "P=/tmp/sv_vpss; : > $P; "
    "(if test -e /proc/msp/vpss01; then grep -iE 'ProcessHZ|AcquireHZ|State' /proc/msp/vpss01 | head -8; "
    "else echo NO_VPSS; fi) > $P 2>&1 & HP=$!; "
    "i=0; while [ $i -lt %d ]; do kill -0 $HP 2>/dev/null || break; sleep 1; i=$((i+1)); done; "
    "if kill -0 $HP 2>/dev/null; then kill -9 $HP 2>/dev/null; echo MSP_TIMEOUT; else cat $P; fi"
) % MSP_SEC

_DEMUX_CMD = (
    "D=/tmp/sv_demux; : > $D; "
    "(if test -e /proc/msp/demux_main; then head -c 2048 /proc/msp/demux_main; "
    "else echo NO_DEMUX; fi) > $D 2>&1 & HP=$!; "
    "i=0; while [ $i -lt %d ]; do kill -0 $HP 2>/dev/null || break; sleep 1; i=$((i+1)); done; "
    "if kill -0 $HP 2>/dev/null; then kill -9 $HP 2>/dev/null; echo MSP_TIMEOUT; else cat $D; fi"
) % MSP_SEC
_SYNC_CMD = (
    "Y=/tmp/sv_sync; : > $Y; "
    "(if test -e /proc/msp/sync00; then grep -E 'CrtStatus|SyncRef|PcrAud|PcrVid' /proc/msp/sync00 | head -8; "
    "else echo NO_SYNC; fi) > $Y 2>&1 & HP=$!; "
    "i=0; while [ $i -lt %d ]; do kill -0 $HP 2>/dev/null || break; sleep 1; i=$((i+1)); done; "
    "if kill -0 $HP 2>/dev/null; then kill -9 $HP 2>/dev/null; echo MSP_TIMEOUT; else cat $Y; fi"
) % MSP_SEC

_FRONTEND_CMD = (
    "F=/tmp/sv_fe; : > $F; "
    "(if test -d /proc/stb/frontend/0; then "
    "for x in snr agc ber lock; do "
    "if test -e /proc/stb/frontend/0/$x; then echo -n \"$x=\"; cat /proc/stb/frontend/0/$x 2>/dev/null; echo; "
    "fi; done; else echo NO_FRONTEND; fi) > $F 2>&1 & HP=$!; "
    "i=0; while [ $i -lt %d ]; do kill -0 $HP 2>/dev/null || break; sleep 1; i=$((i+1)); done; "
    "if kill -0 $HP 2>/dev/null; then kill -9 $HP 2>/dev/null; echo MSP_TIMEOUT; else cat $F; fi"
) % MSP_SEC

_HDMI_CMD = (
    "H=/tmp/sv_hdmi; : > $H; "
    "(if test -e /proc/msp/hdmi0; then grep -E 'HotPlug|Rsen|PhyOutput|TMDS' /proc/msp/hdmi0 | head -8; "
    "else echo NO_HDMI; fi) > $H 2>&1 & HP=$!; "
    "i=0; while [ $i -lt %d ]; do kill -0 $HP 2>/dev/null || break; sleep 1; i=$((i+1)); done; "
    "if kill -0 $HP 2>/dev/null; then kill -9 $HP 2>/dev/null; echo MSP_TIMEOUT; else cat $H; fi"
) % MSP_SEC


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _load_prev() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_prev(data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(STATE_PATH)), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, STATE_PATH)


def _write_snapshot(snap: dict, **extra) -> None:
    """Merge snapshot into state without dropping a recoverNonce queued mid-probe."""
    prev = _load_prev()
    payload = {**prev, **extra, "snapshot": snap}
    _save_prev(payload)


def snap_is_freeze(snap: dict) -> bool:
    """FREEZE pill only for A/V path — Telnet/UI are context, not freeze."""
    return any((snap.get(k) or {}).get("tone") == "FAIL" for k in FREEZE_KEYS)


def snap_is_healthy(snap: dict) -> bool:
    if snap_is_freeze(snap):
        return False
    return all((snap.get(k) or {}).get("tone") == "OK" for k in FREEZE_KEYS)


def snap_age_sec(updated_at: str, now: datetime | None = None) -> float | None:
    raw = (updated_at or "").strip()
    if not raw or raw.startswith("--"):
        return None
    try:
        parsed = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    current = now or datetime.now()
    if current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return (current - parsed).total_seconds()


def snap_is_stale(updated_at: str, poll_sec: int = POLL_SEC, now: datetime | None = None) -> bool:
    age = snap_age_sec(updated_at, now)
    if age is None:
        return False
    return age > (poll_sec * 2 + STALE_GRACE_SEC)


def _item(tone: str, detail: str, blink: bool, **extra) -> dict:
    out = {"tone": tone, "detail": detail, "blink": blink}
    out.update(extra)
    return out


def _parse_av(text: str) -> dict:
    play = ""
    vid = ""
    aud = ""
    vidpid = ""
    if "MSP_TIMEOUT" in text:
        return {"timeout": True, "play": "", "vid": "", "aud": "", "vidpid": ""}
    for ln in text.splitlines():
        s = ln.strip()
        if "CurStatus" in s:
            if "PLAY" in s.split("CurStatus", 1)[-1]:
                play = "PLAY"
            elif "STOP" in s.split("CurStatus", 1)[-1]:
                play = "STOP"
        if "Vid Enable" in s:
            vid = "TRUE" if "TRUE" in s.split("Vid Enable", 1)[-1] else "FALSE"
        if "Aud Enable" in s:
            aud = "TRUE" if "TRUE" in s.split("Aud Enable", 1)[-1] else "FALSE"
        if "VidPid" in s:
            # First token only — avoid "|FrcEnable" contamination on some dumps.
            tail = s.split(":", 1)[-1].strip() if ":" in s else s
            vidpid = (tail.split() or [""])[0]
    return {
        "timeout": False,
        "play": play,
        "vid": vid,
        "aud": aud,
        "vidpid": vidpid,
    }


def _parse_node(raw: str, ok_tok: str, miss_tok: str) -> tuple[bool, bool, bool]:
    lines = {ln.strip() for ln in raw.splitlines()}
    timeout = "MSP_TIMEOUT" in lines
    present = (not timeout) and (ok_tok in lines)
    missing = (not timeout) and (miss_tok in lines) and not present
    return timeout, present, missing


def _node_item(timeout: bool, present: bool, missing: bool, present_txt: str, missing_txt: str) -> dict:
    if timeout:
        return _item("UNKNOWN", "MSP timed out", False)
    if present:
        return _item("OK", present_txt, False)
    if missing:
        return _item("FAIL", missing_txt, True)
    return _item("UNKNOWN", "unknown", False)


def _re_first(text: str, pat: str) -> str:
    m = re.search(pat, text, re.I)
    return m.group(1).strip() if m else ""


def _token_lines(raw: str) -> set[str]:
    return {ln.strip() for ln in (raw or "").splitlines()}


def _fmt_fps(raw: str) -> str:
    try:
        val = float(raw)
    except ValueError:
        return raw + "fps"
    if val == int(val):
        return "%dfps" % int(val)
    return ("%s" % val).rstrip("0").rstrip(".") + "fps"


def _fmt_hz(raw: str) -> str:
    try:
        n = int(raw)
    except ValueError:
        return raw
    if n >= 1000 and n % 1000 == 0:
        return "%dkHz" % (n // 1000)
    return "%dHz" % n


def _parse_win(raw: str) -> dict:
    lines = _token_lines(raw)
    timeout = "MSP_TIMEOUT" in lines
    missing = (not timeout) and ("NO_WIN" in lines)
    if timeout or missing:
        return {
            "timeout": timeout,
            "missing": missing,
            "enable": "",
            "state": "",
            "wh": "",
            "fps": "",
            "idx": "",
        }
    wh_m = re.search(r"W/H\(Aspect[^)]*\)\s*:\s*(\d+)\s*/\s*(\d+)", raw)
    return {
        "timeout": False,
        "missing": False,
        "enable": _re_first(raw, r"Enable\s+:\s*(\w+)"),
        "state": _re_first(raw, r"State\s+:\s*(\w+)"),
        "wh": ("%sx%s" % (wh_m.group(1), wh_m.group(2))) if wh_m else "",
        "fps": _re_first(raw, r"FrameRate\s+:\s*([\d.]+)"),
        "idx": _re_first(raw, r"FrameIndex\s+:\s*(\S+)"),
    }


def _parse_adec(raw: str) -> dict:
    lines = _token_lines(raw)
    timeout = "MSP_TIMEOUT" in lines
    missing = (not timeout) and ("NO_ADEC" in lines)
    if timeout or missing:
        return {
            "timeout": timeout,
            "missing": missing,
            "work": "",
            "codec": "",
            "rate": "",
            "ch": "",
            "frames": "",
        }
    return {
        "timeout": False,
        "missing": False,
        "work": _re_first(raw, r"WorkState\s+:\s*(\S+)"),
        "codec": _re_first(raw, r"DecoderName\s+:\s*(\S+)"),
        "rate": _re_first(raw, r"SampleRate\s+:\s*(\d+)"),
        "ch": _re_first(raw, r"Channels\s+:\s*(\d+)"),
        "frames": _re_first(raw, r"FrameNum\(Total/Error\)\s+:\s*(\d+/\d+)"),
    }


def _win_item(parsed: dict, prev: dict | None = None) -> dict:
    extra = {
        "enable": parsed.get("enable") or "-",
        "state": parsed.get("state") or "-",
        "wh": parsed.get("wh") or "-",
        "idx": parsed.get("idx") or "-",
    }
    if parsed.get("timeout"):
        return _item("UNKNOWN", "MSP timed out", False, **extra)
    if parsed.get("missing"):
        return _item("FAIL", "win0100 missing", True, **extra)
    bits = []
    enable = (parsed.get("enable") or "").strip()
    state = (parsed.get("state") or "").strip()
    if enable:
        bits.append(enable)
    if state:
        bits.append(state)
    if parsed.get("wh"):
        bits.append(parsed["wh"])
    if parsed.get("fps"):
        bits.append(_fmt_fps(parsed["fps"]))
    if parsed.get("idx"):
        bits.append("idx " + parsed["idx"])
    detail = "  ".join(bits) if bits else "win0100 present"
    en = enable.lower()
    st = state.lower()
    if en == "false":
        return _item("FAIL", detail, True, **extra)
    # FrameIndex delta: Enable true but idx frozen across polls → FAIL.
    cur_idx = _parse_hex_int(parsed.get("idx") or "")
    prev_idx = _parse_hex_int((prev or {}).get("idx") or "")
    if en == "true" and cur_idx is not None and prev_idx is not None and cur_idx == prev_idx:
        return _item("FAIL", detail + "  idx stuck", True, **extra)
    if en == "true" and (not st or st == "run"):
        return _item("OK", detail, False, **extra)
    if bits:
        return _item("WARN", detail, False, **extra)
    return _item("OK", detail, False, **extra)


def _adec_item(parsed: dict, prev: dict | None = None) -> dict:
    extra = {
        "work": parsed.get("work") or "-",
        "codec": parsed.get("codec") or "-",
        "rate": parsed.get("rate") or "-",
        "frames": parsed.get("frames") or "-",
    }
    if parsed.get("timeout"):
        return _item("UNKNOWN", "MSP timed out", False, **extra)
    if parsed.get("missing"):
        return _item("FAIL", "adec00 missing", True, **extra)
    bits = []
    work = (parsed.get("work") or "").strip()
    if work:
        bits.append(work)
    if parsed.get("codec"):
        bits.append(parsed["codec"])
    if parsed.get("rate"):
        bits.append(_fmt_hz(parsed["rate"]))
    if parsed.get("ch"):
        bits.append(parsed["ch"] + "ch")
    if parsed.get("frames"):
        bits.append(parsed["frames"])
    detail = "  ".join(bits) if bits else "adec00 present"
    wk = work.lower()
    if wk in ("stop", "stopped", "idle"):
        return _item("FAIL", detail, True, **extra)
    cur_tot = _frame_total(parsed.get("frames") or "")
    prev_tot = _frame_total((prev or {}).get("frames") or "")
    err = _frame_error(parsed.get("frames") or "")
    if wk == "start" and cur_tot is not None and prev_tot is not None and cur_tot == prev_tot:
        return _item("FAIL", detail + "  frames stuck", True, **extra)
    if wk == "start" and err is not None and err > 0 and prev_tot is not None:
        prev_err = _frame_error((prev or {}).get("frames") or "")
        if prev_err is not None and err > prev_err + 50:
            return _item("WARN", detail + "  err rising", False, **extra)
    if wk == "start":
        return _item("OK", detail, False, **extra)
    if bits:
        return _item("WARN", detail, False, **extra)
    return _item("OK", detail, False, **extra)


def _parse_hex_int(raw: str) -> int | None:
    s = (raw or "").strip().lower()
    if not s or s == "-":
        return None
    try:
        return int(s, 16) if s.startswith("0x") else int(s, 16)
    except ValueError:
        try:
            return int(s, 10)
        except ValueError:
            return None


def _frame_total(frames: str) -> int | None:
    s = (frames or "").strip()
    if "/" not in s:
        return None
    try:
        return int(s.split("/", 1)[0])
    except ValueError:
        return None


def _frame_error(frames: str) -> int | None:
    s = (frames or "").strip()
    if "/" not in s:
        return None
    try:
        return int(s.split("/", 1)[1])
    except ValueError:
        return None


def _parse_int_field(raw: str, key: str) -> int | None:
    m = re.search(rf"{key}\s*[:=]\s*(\d+)", raw or "", re.I)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _parse_stat(raw: str) -> dict:
    lines = _token_lines(raw)
    return {
        "timeout": "MSP_TIMEOUT" in lines,
        "missing": (not ("MSP_TIMEOUT" in lines)) and ("NO_STAT" in lines),
        "streamin": _parse_int_field(raw, "STREAMIN"),
        "framedeced": _parse_int_field(raw, "FRAMEDECED"),
        "locked": _parse_int_field(raw, "LOCKED"),
        "vstop": _parse_int_field(raw, "VSTOP"),
        "raw": (raw or "").strip(),
    }


def _stat_item(parsed: dict, prev: dict | None = None) -> dict:
    """MSP /proc/msp/stat — on clap4k STREAMIN/FRAMEDECED often freeze while path lives.

    FAIL only on VSTOP>0. Stuck counters → WARN (not FREEZE). Rising → OK.
    """
    if parsed.get("timeout"):
        return _item("UNKNOWN", "MSP timed out", False)
    if parsed.get("missing"):
        return _item("WARN", "stat node missing", False)
    fd = parsed.get("framedeced")
    si = parsed.get("streamin")
    vs = parsed.get("vstop")
    bits = []
    if si is not None:
        bits.append("in %d" % si)
    if fd is not None:
        bits.append("dec %d" % fd)
    if vs is not None and vs > 0:
        bits.append("VSTOP %d" % vs)
    detail = "  ".join(bits) if bits else "stat present"
    prev_fd = None
    try:
        prev_fd = int((prev or {}).get("framedeced"))
    except (TypeError, ValueError):
        prev_fd = None
    if vs is not None and vs > 0:
        return _item("FAIL", detail, True, framedeced=fd, streamin=si)
    if fd is not None and prev_fd is not None:
        if fd > prev_fd:
            return _item("OK", detail + "  +%d" % (fd - prev_fd), False, framedeced=fd, streamin=si)
        if fd == prev_fd:
            # clap4k: counters can stall forever while win/adec advance — WARN only.
            return _item(
                "WARN",
                detail + "  counters stale",
                False,
                framedeced=fd,
                streamin=si,
            )
    if fd is not None or si is not None:
        return _item("OK", detail, False, framedeced=fd, streamin=si)
    return _item("UNKNOWN", "no counters", False)


def _parse_vpss(raw: str) -> dict:
    lines = _token_lines(raw)
    hz_a = hz_b = None
    # Live clap4k: ProcessHZ(Try/OK)    :197/51
    m = re.search(r"ProcessHZ(?:\([^)]*\))?\s*[:=]\s*(\d+)\s*/\s*(\d+)", raw or "", re.I)
    if m:
        hz_a, hz_b = int(m.group(1)), int(m.group(2))
    acq = None
    m2 = re.search(r"AcquireHZ\s*[:=]\s*(\d+)", raw or "", re.I)
    if m2:
        acq = int(m2.group(1))
    return {
        "timeout": "MSP_TIMEOUT" in lines,
        "missing": (not ("MSP_TIMEOUT" in lines)) and ("NO_VPSS" in lines),
        "hz_a": hz_a,
        "hz_b": hz_b,
        "acquire": acq,
    }


def _vpss_item(parsed: dict) -> dict:
    if parsed.get("timeout"):
        return _item("UNKNOWN", "MSP timed out", False)
    if parsed.get("missing"):
        return _item("FAIL", "vpss01 missing", True)
    a, b = parsed.get("hz_a"), parsed.get("hz_b")
    acq = parsed.get("acquire")
    if a is None and acq is None:
        return _item("UNKNOWN", "no ProcessHZ", False)
    bits = []
    if a is not None:
        bits.append("ProcessHZ %d/%d" % (a, b if b is not None else 0))
    if acq is not None:
        bits.append("AcquireHZ %d" % acq)
    detail = "  ".join(bits)
    if a is not None and a == 0 and (b is None or b == 0) and (acq is None or acq == 0):
        return _item("FAIL", detail + "  dead", True, hz=a or 0)
    if (b is not None and b >= 40) or (acq is not None and acq >= 40) or (a is not None and a > 0):
        return _item("OK", detail, False, hz=a or acq or 0)
    return _item("WARN", detail, False, hz=a or 0)


def _parse_vdec(raw: str) -> dict:
    lines = _token_lines(raw)
    timeout = "MSP_TIMEOUT" in lines
    missing = (not timeout) and ("NO_VDEC" in lines)
    state = _re_first(raw, r"(?:^|\n)\s*State\s*[:=]\s*(\S+)") or _re_first(
        raw, r"\bstate\s*[:=]\s*(\S+)"
    )
    return {
        "timeout": timeout,
        "missing": missing,
        "present": (not timeout) and (not missing) and ("VDEC_OK" in lines or bool(state)),
        "state": state,
        "bitrate": _re_first(raw, r"BitRate\s*[:=]\s*(\S+)"),
        "errframe": _parse_int_field(raw, "ErrFrame"),
    }


def _vdec_item(parsed: dict) -> dict:
    if parsed.get("timeout"):
        return _item("UNKNOWN", "MSP timed out", False)
    if parsed.get("missing"):
        return _item("FAIL", "vdec00 missing", True)
    state = (parsed.get("state") or "").strip()
    bits = ["vdec00"]
    if state:
        bits.append(state)
    if parsed.get("bitrate"):
        bits.append("br " + parsed["bitrate"])
    err = parsed.get("errframe")
    if err is not None:
        bits.append("err %d" % err)
    detail = "  ".join(bits)
    st = state.lower()
    if st and st not in ("run", "running", "start", "play", "ok") and "run" not in st:
        if err is not None and err > 100:
            return _item("FAIL", detail, True, frames=str(err))
        return _item("WARN", detail, False)
    if err is not None and err > 500:
        return _item("WARN", detail + "  high err", True)
    if parsed.get("present") or state:
        return _item("OK", detail if state else "vdec00 present", False)
    return _item("UNKNOWN", "unknown", False)


def _parse_sync(raw: str) -> dict:
    lines = _token_lines(raw)
    status = _re_first(raw, r"CrtStatus\s*[:=]\s*(\S+)")
    return {
        "timeout": "MSP_TIMEOUT" in lines,
        "missing": (not ("MSP_TIMEOUT" in lines)) and ("NO_SYNC" in lines),
        "status": status,
        "ref": _re_first(raw, r"SyncRef\s*[:=]\s*(\S+)"),
    }


def _sync_item(parsed: dict, path_dead: bool) -> dict:
    if parsed.get("timeout"):
        return _item("UNKNOWN", "MSP timed out", False)
    if parsed.get("missing"):
        return _item("WARN", "sync00 missing", False)
    st = (parsed.get("status") or "").strip()
    ref = (parsed.get("ref") or "").strip()
    detail = "  ".join(x for x in (st, ref) if x) or "sync present"
    low = st.lower()
    if "stop" in low:
        if path_dead:
            return _item("FAIL", detail, True)
        return _item("WARN", detail + "  (zap/hold?)", False)
    if st:
        return _item("OK", detail, False)
    return _item("UNKNOWN", "no CrtStatus", False)


def _parse_demux(raw: str) -> dict:
    lines = _token_lines(raw)
    tei = _parse_int_field(raw, "TEICnt")
    cc = _parse_int_field(raw, "CCDiscCnt")
    # Table row: DmxId PortId TEICnt CCDiscCnt ... then numeric line
    if tei is None or cc is None:
        for ln in (raw or "").splitlines():
            parts = ln.split()
            if len(parts) >= 4 and parts[0].isdigit() and parts[2].isdigit():
                try:
                    tei = tei if tei is not None else int(parts[2])
                    cc = cc if cc is not None else int(parts[3])
                except ValueError:
                    pass
                break
    return {
        "timeout": "MSP_TIMEOUT" in lines,
        "missing": (not ("MSP_TIMEOUT" in lines)) and ("NO_DEMUX" in lines),
        "tei": tei,
        "cc": cc,
    }


def _demux_item(parsed: dict) -> dict:
    """Informational — transport errors, not MSP wedge."""
    if parsed.get("timeout"):
        return _item("UNKNOWN", "MSP timed out", False)
    if parsed.get("missing"):
        return _item("WARN", "demux_main missing", False)
    tei, cc = parsed.get("tei"), parsed.get("cc")
    bits = []
    if tei is not None:
        bits.append("TEI %d" % tei)
    if cc is not None:
        bits.append("CC %d" % cc)
    detail = "  ".join(bits) if bits else "demux present"
    if (tei is not None and tei > 100) or (cc is not None and cc > 100):
        return _item("WARN", detail + "  TS errors", False)
    return _item("OK", detail, False)


def _parse_frontend(raw: str) -> dict:
    lines = _token_lines(raw)
    vals = {}
    for ln in (raw or "").splitlines():
        if "=" in ln:
            k, _, v = ln.partition("=")
            vals[k.strip().lower()] = v.strip()
    return {
        "timeout": "MSP_TIMEOUT" in lines,
        "missing": (not ("MSP_TIMEOUT" in lines)) and ("NO_FRONTEND" in lines),
        "snr": vals.get("snr", ""),
        "agc": vals.get("agc", ""),
        "ber": vals.get("ber", ""),
        "lock": vals.get("lock", ""),
    }


def _frontend_item(parsed: dict) -> dict:
    if parsed.get("timeout"):
        return _item("UNKNOWN", "read timed out", False)
    if parsed.get("missing"):
        return _item("WARN", "frontend0 missing", False)
    bits = []
    for k in ("lock", "snr", "agc", "ber"):
        if parsed.get(k):
            bits.append("%s %s" % (k, parsed[k]))
    detail = "  ".join(bits) if bits else "frontend present"
    lock = (parsed.get("lock") or "").lower()
    if lock in ("0", "no", "false", "unlock", "unlocked"):
        return _item("WARN", detail + "  unlocked", False)
    return _item("OK", detail, False)


def _parse_hdmi(raw: str) -> dict:
    lines = _token_lines(raw)
    return {
        "timeout": "MSP_TIMEOUT" in lines,
        "missing": (not ("MSP_TIMEOUT" in lines)) and ("NO_HDMI" in lines),
        "hotplug": _re_first(raw, r"HotPlug\s*[:=]\s*(\S+)"),
        "rsen": _re_first(raw, r"Rsen\s*[:=]\s*(\S+)"),
        "phy": _re_first(raw, r"PhyOutput\s*[:=]\s*(\S+)"),
    }


def _hdmi_item(parsed: dict) -> dict:
    if parsed.get("timeout"):
        return _item("UNKNOWN", "MSP timed out", False)
    if parsed.get("missing"):
        return _item("WARN", "hdmi0 missing", False)
    bits = []
    for k, lab in (("hotplug", "HP"), ("rsen", "Rsen"), ("phy", "Phy")):
        if parsed.get(k):
            bits.append("%s %s" % (lab, parsed[k]))
    detail = "  ".join(bits) if bits else "hdmi present"
    hp = (parsed.get("hotplug") or "").lower()
    if hp in ("no", "0", "false", "n"):
        return _item("WARN", detail + "  no sink", False)
    return _item("OK", detail, False)


def _stall_item(timeouts: list[str], ui_ok: bool) -> dict:
    """Multiple critical MSP timeouts while UI alive ≈ wedge signature."""
    if not timeouts:
        return _item("OK", "no MSP timeouts", False)
    detail = "timeout: " + ",".join(timeouts)
    if ui_ok and len(timeouts) >= 3:
        return _item("FAIL", detail, True)
    if len(timeouts) >= 2:
        return _item("WARN", detail, False)
    return _item("WARN", detail, False)


def _hold_last_good(prev_item: dict | None, item: dict) -> dict:
    """Keep the last conclusive sample when this poll is inconclusive.

    /proc/msp/win0100 and adec00 often time out even while the path is healthy.
    UNKNOWN (timeout / no fields) must not wipe a prior OK/WARN/FAIL.
    """
    if (item.get("tone") or "") != "UNKNOWN":
        return item
    prev = prev_item or {}
    if (prev.get("tone") or "") not in ("OK", "WARN", "FAIL"):
        return item
    return dict(prev)


def _vidpid_null(vidpid: str) -> bool:
    compact = (vidpid or "").lower().replace("0x", "").strip()
    return compact.startswith("1fff")


def _av_tone_from_fields(av: dict, pid_null: bool) -> tuple[str, bool, str]:
    """Match freeze_lib: VidPid 0x1fff alone under PLAY is WARN, not FAIL."""
    if av["timeout"]:
        return "UNKNOWN", False, "MSP timed out - picture unknown"
    play, vid, aud = av["play"], av["vid"], av["aud"]
    if play == "PLAY" and vid == "TRUE" and aud == "TRUE" and not pid_null:
        detail = "PLAY  vid/aud on"
        if av.get("vidpid"):
            detail += "  %s" % av["vidpid"]
        return "OK", False, detail
    if play == "PLAY" and vid == "TRUE" and aud == "TRUE" and pid_null:
        return "WARN", False, "PLAY  vid/aud on  VidPid 0x1fff (metadata)"
    # freeze_lib: STOP + (null PID | Vid FALSE | no vdec handled elsewhere)
    # or Vid FALSE + null PID. Overlay also fails Aud FALSE / STOP alone.
    if play == "STOP" or vid == "FALSE" or aud == "FALSE":
        bits = [play or "no PLAY", "vid " + (vid or "?"), "aud " + (aud or "?")]
        if pid_null:
            bits.append("VidPid 0x1fff")
        return "FAIL", True, "  ".join(bits)
    if not play:
        return "UNKNOWN", False, "no CurStatus (timed MSP)"
    return "WARN", False, "%s  vid %s  aud %s" % (play or "?", vid or "?", aud or "?")


def probe(phase: str = "idle", recover_note: str = "") -> dict:
    t0 = time.time()
    try:
        sock = telnet_run.login()
        login_ms = int((time.time() - t0) * 1000)
    except Exception as exc:
        snap = _fail_telnet(str(exc), phase, recover_note)
        _write_snapshot(snap)
        return snap

    idx = 0

    def cmd(c: str, timeout: int = 8) -> str:
        nonlocal idx
        idx += 1
        return telnet_run.run(sock, c, idx, timeout=timeout)

    try:
        hostname = (cmd("hostname", 5) or "").strip() or "unknown"
        bian = (cmd("pidof bianbiang 2>/dev/null", 5) or "").strip()
        av_raw = cmd(_AV_CMD, MSP_SEC + 6)
        stat_raw = cmd(_STAT_CMD, MSP_SEC + 6)
        vpss_raw = cmd(_VPSS_CMD, MSP_SEC + 6)
        vdec_raw = cmd(_VDEC_CMD, MSP_SEC + 6)
        win_raw = cmd(_WIN_CMD, MSP_SEC + 6)
        adec_raw = cmd(_ADEC_CMD, MSP_SEC + 6)
        sync_raw = cmd(_SYNC_CMD, MSP_SEC + 6)
        demux_raw = cmd(_DEMUX_CMD, MSP_SEC + 6)
        fe_raw = cmd(_FRONTEND_CMD, MSP_SEC + 6)
        hdmi_raw = cmd(_HDMI_CMD, MSP_SEC + 6)
    except Exception as exc:
        try:
            sock.close()
        except Exception:
            pass
        snap = _fail_telnet(str(exc), phase, recover_note)
        _write_snapshot(snap)
        return snap

    try:
        sock.sendall(b"exit\r\n")
        sock.close()
    except Exception:
        pass

    prev_snap = _load_prev().get("snapshot") or {}
    av = _parse_av(av_raw)
    pid_null = _vidpid_null(av.get("vidpid") or "")
    av_tone, av_blink, av_detail = _av_tone_from_fields(av, pid_null)

    stat_p = _parse_stat(stat_raw)
    vpss_p = _parse_vpss(vpss_raw)
    vdec_p = _parse_vdec(vdec_raw)
    win_p = _parse_win(win_raw)
    adec_p = _parse_adec(adec_raw)
    sync_p = _parse_sync(sync_raw)
    demux_p = _parse_demux(demux_raw)
    fe_p = _parse_frontend(fe_raw)
    hdmi_p = _parse_hdmi(hdmi_raw)

    win_item = _hold_last_good(
        prev_snap.get("win"),
        _win_item(win_p, prev_snap.get("win")),
    )
    adec_item = _hold_last_good(
        prev_snap.get("adec"),
        _adec_item(adec_p, prev_snap.get("adec")),
    )
    stat_item = _hold_last_good(
        prev_snap.get("stat"),
        _stat_item(stat_p, prev_snap.get("stat")),
    )
    vpss_item = _hold_last_good(prev_snap.get("vpss"), _vpss_item(vpss_p))
    vdec_item = _hold_last_good(prev_snap.get("vdec"), _vdec_item(vdec_p))

    path_dead = any(
        (x.get("tone") == "FAIL")
        for x in (stat_item, vpss_item, vdec_item, win_item, adec_item)
    )
    sync_item = _hold_last_good(
        prev_snap.get("sync"),
        _sync_item(sync_p, path_dead),
    )

    bian_alive = bool(bian) and bian.split()[0].isdigit()
    ui_item = (
        _item("OK", "pid %s" % bian.split()[0], False)
        if bian_alive
        else _item("FAIL", "bianbiang not running", True)
    )

    timeouts = []
    for name, raw in (
        ("av", av_raw),
        ("stat", stat_raw),
        ("vpss", vpss_raw),
        ("vdec", vdec_raw),
        ("win", win_raw),
        ("adec", adec_raw),
        ("sync", sync_raw),
    ):
        if "MSP_TIMEOUT" in (raw or ""):
            timeouts.append(name)

    snap = {
        "updatedAt": _now_iso(),
        "hostname": hostname,
        "host": HOST,
        "phase": phase,
        "recoverNote": recover_note,
        "loginMs": login_ms,
        "telnet": _item("OK", "%d ms" % login_ms, False),
        "av": _item(
            av_tone,
            av_detail,
            av_blink,
            play=av["play"] or "-",
            vid=av["vid"] or "-",
            aud=av["aud"] or "-",
        ),
        "stat": stat_item,
        "vpss": vpss_item,
        "vdec": vdec_item,
        "win": win_item,
        "adec": adec_item,
        "sync": sync_item,
        "demux": _demux_item(demux_p),
        "frontend": _frontend_item(fe_p),
        "hdmi": _hdmi_item(hdmi_p),
        "stall": _stall_item(timeouts, bian_alive),
        "ui": ui_item,
    }
    _write_snapshot(snap)
    return snap


def _fail_telnet(err: str, phase: str, recover_note: str) -> dict:
    detail = (err or "unreachable")[:80]
    note = recover_note or ("Telnet down - %s" % detail)
    unk = _item("UNKNOWN", "no session", False)
    return {
        "updatedAt": _now_iso(),
        "hostname": "clap4k",
        "host": HOST,
        "phase": phase,
        "recoverNote": note,
        "loginMs": None,
        "telnet": _item("FAIL", detail, True),
        "av": {**unk, "play": "-", "vid": "-", "aud": "-"},
        "stat": dict(unk),
        "vpss": dict(unk),
        "vdec": dict(unk),
        "win": dict(unk),
        "adec": dict(unk),
        "sync": dict(unk),
        "demux": dict(unk),
        "frontend": dict(unk),
        "hdmi": dict(unk),
        "stall": dict(unk),
        "ui": dict(unk),
    }


def _js_snapshot(snap: dict) -> str:
    body = json.dumps(snap, indent=2, ensure_ascii=True)
    # JSON is valid JS object literal here (no undefined).
    return "// SNAPSHOT_BEGIN\nconst SNAPSHOT: Snapshot = %s; // SNAPSHOT_END" % body


def patch_canvas(snap: dict) -> None:
    if not os.path.isfile(CANVAS):
        print("canvas missing:", CANVAS, flush=True)
        return
    with open(CANVAS, "r", encoding="utf-8") as f:
        src = f.read()
    repl = _js_snapshot(snap)
    new, n = _SNAP_RE.subn(lambda _m: repl, src, count=1)
    if n != 1:
        print("SNAPSHOT markers not found in canvas", flush=True)
        return
    tmp = CANVAS + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    os.replace(tmp, CANVAS)


def _walk_nonce(obj) -> int:
    if isinstance(obj, dict):
        best = 0
        for k, v in obj.items():
            if k in ("recoverNonce", "recoverAt", "recoverRequest") and isinstance(v, (int, float)):
                best = max(best, int(v))
            best = max(best, _walk_nonce(v))
        return best
    if isinstance(obj, list):
        return max((_walk_nonce(x) for x in obj), default=0)
    return 0


def _read_recover_nonce() -> int:
    n = 0
    prev = _load_prev()
    try:
        n = max(n, int(prev.get("recoverNonce") or 0))
    except (TypeError, ValueError):
        pass
    if os.path.isfile(SIDECAR):
        try:
            with open(SIDECAR, "r", encoding="utf-8") as f:
                n = max(n, _walk_nonce(json.load(f)))
        except Exception:
            pass
    return n


def _queue_recover() -> None:
    prev = _load_prev()
    handled = int(prev.get("handledRecoverNonce") or 0)
    prev["recoverNonce"] = handled + 1
    _save_prev(prev)


def _publish_snap(snap: dict) -> None:
    """Persist snapshot for the widget and patch the Cursor canvas."""
    prev = _load_prev()
    prev["snapshot"] = snap
    _save_prev(prev)
    patch_canvas(snap)


def _recover_fail(err: str, note: str) -> dict:
    """Abort recover; phase idle so Recover can be clicked again."""
    snap = _fail_telnet(err, "idle", note)
    _publish_snap(snap)
    return snap


def _onbox_zap_cmd() -> str:
    # On-box only (PC :80 /web/zap is 404). Prefer OpenWebif :9095 then :80.
    return (
        "(wget -qO- 'http://127.0.0.1:9095/web/zap?sRef=%s' >/dev/null 2>&1 "
        "|| wget -qO- 'http://127.0.0.1:80/web/zap?sRef=%s' >/dev/null 2>&1 "
        "|| wget -qO- 'http://127.0.0.1/web/zap?sRef=%s' >/dev/null 2>&1) "
        "&& echo ZAP_OK || echo ZAP_FAIL"
    ) % (ZAP_REF, ZAP_REF, ZAP_REF)


def serve_ui(*, tk: bool = False) -> None:
    """Launch the native freeze widget. Never starts HTTP or a browser.

    Default host is Edge WebView2 (canvas HTML twin). --ui-tk uses Tk.
    If WebView2 cannot start, fall back to Tk so the operator still gets a widget.
    """
    kwargs = dict(
        poll_worker=loop_ui,
        load_prev=_load_prev,
        save_prev=_save_prev,
        queue_recover=_queue_recover,
        poll_sec=POLL_SEC,
        host=HOST,
    )
    if tk:
        import freeze_overlay_win  # noqa: WPS433

        freeze_overlay_win.run_ui(**kwargs)
        return
    try:
        import freeze_overlay_web  # noqa: WPS433
    except Exception as exc:
        print("WebView2 host unavailable (%s) — using Tk fallback." % exc, flush=True)
        import freeze_overlay_win  # noqa: WPS433

        freeze_overlay_win.run_ui(**kwargs)
        return
    try:
        freeze_overlay_web.run_ui(**kwargs)
    except SystemExit as exc:
        if int(getattr(exc, "code", 1) or 1) == 2:
            raise
        print("WebView2 overlay exited (%s) — using Tk fallback." % exc, flush=True)
        import freeze_overlay_web as _web  # noqa: WPS433
        import freeze_overlay_win  # noqa: WPS433

        owned = getattr(_web.try_single_instance, "_handle", None)
        if owned:
            freeze_overlay_win.try_single_instance._handle = owned
        freeze_overlay_win.run_ui(**kwargs)
    except Exception as exc:
        print("WebView2 overlay failed (%s) — using Tk fallback." % exc, flush=True)
        import freeze_overlay_web as _web  # noqa: WPS433
        import freeze_overlay_win  # noqa: WPS433

        owned = getattr(_web.try_single_instance, "_handle", None)
        if owned:
            freeze_overlay_win.try_single_instance._handle = owned
        freeze_overlay_win.run_ui(**kwargs)


def recover() -> dict:
    print("RECOVER: backup live_prog + reboot -f + zap", flush=True)
    snap = probe(phase="recovering", recover_note="Backing up live_prog")
    _publish_snap(snap)
    try:
        sock = telnet_run.login()
    except Exception as exc:
        return _recover_fail("recover login: %s" % exc, "Telnet down - cannot recover")

    bak_out = ""
    try:
        bak_out = telnet_run.run(
            sock,
            "cp -f /data/gx/live_prog %s; sync; echo BAK_OK" % LIVE_PROG_BAK,
            9001,
            timeout=15,
        )
    except Exception as exc:
        try:
            sock.close()
        except Exception:
            pass
        return _recover_fail("backup: %s" % exc, "Backup failed - reboot skipped")

    if "BAK_OK" not in (bak_out or ""):
        try:
            sock.close()
        except Exception:
            pass
        return _recover_fail(
            "backup missing BAK_OK",
            "Backup failed - reboot skipped",
        )

    try:
        sock.sendall(b"/sbin/reboot -f\r\n")
    except Exception as exc:
        try:
            sock.close()
        except Exception:
            pass
        return _recover_fail("reboot send: %s" % exc, "Reboot command failed - not waiting")

    time.sleep(1)
    try:
        sock.close()
    except Exception:
        pass

    wait_snap = {
        **snap,
        "phase": "recovering",
        "recoverNote": "Reboot sent - waiting for clap4k",
        "updatedAt": _now_iso(),
        "telnet": _item("WARN", "rebooting", False),
        "av": _item("UNKNOWN", "waiting for boot", False, play="-", vid="-", aud="-"),
        "vdec": _item("UNKNOWN", "waiting for boot", False),
        "win": _item("UNKNOWN", "waiting for boot", False),
        "adec": _item("UNKNOWN", "waiting for boot", False),
        "ui": _item("UNKNOWN", "waiting for boot", False),
    }
    _publish_snap(wait_snap)

    time.sleep(25)
    t_end = time.time() + 90
    booted = False
    zap_ok = False
    while time.time() < t_end:
        try:
            s = telnet_run.login()
            up = telnet_run.run(s, "cat /proc/uptime | cut -d. -f1", 9002, timeout=8)
            up_s = up.strip()
            if up_s.isdigit() and int(up_s) < 180:
                zap_out = telnet_run.run(s, _onbox_zap_cmd(), 9003, timeout=20)
                zap_ok = "ZAP_OK" in (zap_out or "")
                try:
                    s.sendall(b"exit\r\n")
                    s.close()
                except Exception:
                    pass
                booted = True
                break
            try:
                s.close()
            except Exception:
                pass
        except Exception:
            pass
        time.sleep(4)

    if not booted:
        note = "Boot wait timed out - Recover did not finish"
        return probe(phase="idle", recover_note=note)
    if zap_ok:
        note = "Zapped Iran International HD - watching A/V"
    else:
        note = "Box rebooted but on-box zap failed - check channel"
    return probe(phase="idle", recover_note=note)


def _poll_once() -> dict:
    prev = _load_prev()
    handled = int(prev.get("handledRecoverNonce") or 0)
    nonce = _read_recover_nonce()
    if nonce > handled:
        snap = recover()
        prev = _load_prev()
        prev["handledRecoverNonce"] = nonce
        prev["snapshot"] = snap
        _save_prev(prev)
        patch_canvas(snap)
        return snap
    snap = probe()
    patch_canvas(snap)
    return snap


def loop(stop_event: threading.Event | None = None, wake_event: threading.Event | None = None) -> None:
    print("freeze overlay poll %ss -> %s" % (POLL_SEC, CANVAS), flush=True)
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            snap = _poll_once()
            av = snap["av"]
            print(
                "%s  telnet=%s  av=%s %s  vdec=%s  win=%s  adec=%s  ui=%s  note=%s"
                % (
                    snap["updatedAt"],
                    snap["telnet"]["tone"],
                    av["tone"],
                    av.get("play"),
                    snap["vdec"]["tone"],
                    snap["win"]["tone"],
                    snap["adec"]["tone"],
                    snap["ui"]["tone"],
                    (snap.get("recoverNote") or "")[:40],
                ),
                flush=True,
            )
        except Exception as exc:
            print("poll error:", exc, flush=True)
        if stop_event is not None and stop_event.is_set():
            return
        if wake_event is not None:
            wake_event.wait(timeout=POLL_SEC)
            wake_event.clear()
        else:
            time.sleep(POLL_SEC)


def loop_ui(stop_event: threading.Event | None = None, wake_event: threading.Event | None = None) -> None:
    """UI worker entry: same as loop, interruptible when wake_event is set."""
    loop(stop_event=stop_event, wake_event=wake_event)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--recover", action="store_true")
    p.add_argument("--loop", action="store_true")
    p.add_argument(
        "--ui",
        action="store_true",
        help="open native freeze widget (WebView2); never starts HTTP or a browser",
    )
    p.add_argument(
        "--ui-tk",
        action="store_true",
        help="open native Tk freeze widget (draggable, rounded) — fallback",
    )
    args = p.parse_args()
    if args.ui_tk:
        serve_ui(tk=True)
        return
    if args.ui:
        serve_ui()
        return
    if args.recover:
        snap = recover()
        _publish_snap(snap)
        print(json.dumps(snap, indent=2))
        return
    if args.loop:
        loop()
        return
    snap = probe()
    patch_canvas(snap)
    print(json.dumps(snap, indent=2))
    if not args.once:
        loop()


if __name__ == "__main__":
    main()
