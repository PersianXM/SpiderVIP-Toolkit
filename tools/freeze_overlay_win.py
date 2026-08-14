#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Native Windows freeze overlay (Tk). Canvas palette; no HTTP/browser.

Colors are Cursor canvas dark tokens from freeze-status.canvas.tsx /
useHostTheme() (canvasPaletteDark + categoryPaletteDark).
8-digit fills/text are composited onto theme.bg.editor #181818 — the same
host the canvas card sits on. The window is opaque; alpha would wash the
palette against the desktop and no longer match canvas.
"""
from __future__ import annotations

import ctypes
import os
import re
import sys
import threading
import time
from datetime import datetime
from typing import Callable

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from freeze_overlay_icons import paint_dish, paint_recover, paint_status  # noqa: E402

try:
    import tkinter as tk
except Exception as exc:  # pragma: no cover - missing Tcl
    tk = None  # type: ignore[assignment]
    _TK_ERR: BaseException | None = exc
else:
    _TK_ERR = None

# --- canvasPaletteDark (exact tokens; composite 8-digit onto editor) ---
BG_EDITOR = "#181818"  # theme.bg.editor / elevated
# fill.tertiary #E4E4E411, fill.secondary #E4E4E41E, fill.quaternary #E4E4E40A
# fill.primary #E4E4E430
# stroke.secondary #E4E4E41F, stroke.primary #E4E4E433, stroke.tertiary #E4E4E414
# text.primary #E4E4E4EB, secondary #E4E4E48D, tertiary #E4E4E45E

CONFIRM_ARM_SEC = 0.55
CONFIRM_HOLD_SEC = 5.0
STALE_GRACE_SEC = 20
HIT = 44
CORNER_R = 36
TILE_R = 14
PROBES_R = 18
PILL_H = 22
WIDGET_W = 360
SHELL_PAD = 22
WIN_ALPHA = 1.0
DIGIT_CELL = 7.0
DIGIT_GAP = 2.2
DIGIT_PAD = 8.0
DETAIL_MAX = 120
MIN_H = 560

TITLE_RECOVER = "Recover (reboot)"
TITLE_CONFIRM = "Confirm reboot"
TITLE_RECOVERING = "Recovering"
NOTE_CONFIRM = "Confirm reboot — backup live_prog, force reboot, then zap."
CLOCK_CAPTION = "Last poll · this PC (not box time)"

MUTEX_NAME = "Local\\SpiderVIPFreezeOverlay.mutex"
ERROR_ALREADY_EXISTS = 183


def _hex8_on(bg: str, fg8: str) -> str:
    raw = fg8.lstrip("#")
    r, g, b = int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    a = int(raw[6:8], 16) / 255.0 if len(raw) >= 8 else 1.0
    br, bgc, bb = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
    mix = lambda c, bc: int(round(c * a + bc * (1.0 - a)))  # noqa: E731
    return "#%02X%02X%02X" % (mix(r, br), mix(g, bgc), mix(b, bb))


def _rel_lum(hex_color: str) -> float:
    def chan(v: int) -> float:
        x = v / 255.0
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4

    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(fg: str, bg: str) -> float:
    l1, l2 = _rel_lum(fg), _rel_lum(bg)
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


SHELL_BG = _hex8_on(BG_EDITOR, "#E4E4E411")  # fill.tertiary on editor
TILE_BG = _hex8_on(BG_EDITOR, "#E4E4E41E")  # fill.secondary
DIGIT_OFF = _hex8_on(TILE_BG, "#E4E4E40A")  # fill.quaternary on the digit tile
STROKE = _hex8_on(BG_EDITOR, "#E4E4E41F")  # stroke.secondary
STROKE_HI = _hex8_on(BG_EDITOR, "#E4E4E433")  # stroke.primary
STROKE_LO = _hex8_on(BG_EDITOR, "#E4E4E414")  # stroke.tertiary
FOCUS = "#E4E4E4"  # stroke.focused
TEXT = _hex8_on(SHELL_BG, "#E4E4E4EB")  # text.primary
TEXT_2 = _hex8_on(SHELL_BG, "#E4E4E48D")  # text.secondary
TEXT_3 = _hex8_on(SHELL_BG, "#E4E4E45E")  # text.tertiary
TILE_TEXT = _hex8_on(TILE_BG, "#E4E4E4EB")
TILE_TEXT_2 = _hex8_on(TILE_BG, "#E4E4E48D")
TILE_TEXT_3 = _hex8_on(TILE_BG, "#E4E4E45E")
DIGIT_ON = _hex8_on(TILE_BG, "#E4E4E4EB")
OK = "#3FA266"  # category.green
WARN = "#F1B467"  # category.yellow
FAIL = "#FC6B83"  # category.red

DOT = {
    "0": [[0, 1, 1, 1, 0], [1, 0, 0, 0, 1], [1, 0, 0, 1, 1], [1, 0, 1, 0, 1], [1, 1, 0, 0, 1], [1, 0, 0, 0, 1], [0, 1, 1, 1, 0]],
    "1": [[0, 0, 1, 0, 0], [0, 1, 1, 0, 0], [0, 0, 1, 0, 0], [0, 0, 1, 0, 0], [0, 0, 1, 0, 0], [0, 0, 1, 0, 0], [0, 1, 1, 1, 0]],
    "2": [[0, 1, 1, 1, 0], [1, 0, 0, 0, 1], [0, 0, 0, 0, 1], [0, 0, 1, 1, 0], [0, 1, 0, 0, 0], [1, 0, 0, 0, 0], [1, 1, 1, 1, 1]],
    "3": [[0, 1, 1, 1, 0], [1, 0, 0, 0, 1], [0, 0, 0, 0, 1], [0, 0, 1, 1, 0], [0, 0, 0, 0, 1], [1, 0, 0, 0, 1], [0, 1, 1, 1, 0]],
    "4": [[0, 0, 0, 1, 0], [0, 0, 1, 1, 0], [0, 1, 0, 1, 0], [1, 0, 0, 1, 0], [1, 1, 1, 1, 1], [0, 0, 0, 1, 0], [0, 0, 0, 1, 0]],
    "5": [[1, 1, 1, 1, 1], [1, 0, 0, 0, 0], [1, 1, 1, 1, 0], [0, 0, 0, 0, 1], [0, 0, 0, 0, 1], [1, 0, 0, 0, 1], [0, 1, 1, 1, 0]],
    "6": [[0, 1, 1, 1, 0], [1, 0, 0, 0, 0], [1, 0, 0, 0, 0], [1, 1, 1, 1, 0], [1, 0, 0, 0, 1], [1, 0, 0, 0, 1], [0, 1, 1, 1, 0]],
    "7": [[1, 1, 1, 1, 1], [0, 0, 0, 0, 1], [0, 0, 0, 1, 0], [0, 0, 1, 0, 0], [0, 1, 0, 0, 0], [0, 1, 0, 0, 0], [0, 1, 0, 0, 0]],
    "8": [[0, 1, 1, 1, 0], [1, 0, 0, 0, 1], [1, 0, 0, 0, 1], [0, 1, 1, 1, 0], [1, 0, 0, 0, 1], [1, 0, 0, 0, 1], [0, 1, 1, 1, 0]],
    "9": [[0, 1, 1, 1, 0], [1, 0, 0, 0, 1], [1, 0, 0, 0, 1], [0, 1, 1, 1, 1], [0, 0, 0, 0, 1], [0, 0, 0, 0, 1], [0, 1, 1, 1, 0]],
    "-": [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [1, 1, 1, 1, 1], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
}

ROWS = (
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
SENSOR_KEYS = tuple(k for k, _ in ROWS)
FREEZE_KEYS = ("av", "stat", "vpss", "vdec", "win", "adec", "sync")

DIGIT_W = int(round(DIGIT_PAD * 2 + 5 * DIGIT_CELL + 4 * DIGIT_GAP))
DIGIT_H = int(round(DIGIT_PAD * 2 + 7 * DIGIT_CELL + 6 * DIGIT_GAP))


def _tone_color(tone: str) -> str:
    if tone == "OK":
        return OK
    if tone == "WARN":
        return WARN
    if tone == "FAIL":
        return FAIL
    return TEXT_3


def confirm_ready(armed_at: float | None, now: float, arm_sec: float = CONFIRM_ARM_SEC) -> bool:
    if armed_at is None:
        return False
    return (now - armed_at) + 1e-9 >= arm_sec


def confirm_expired(armed_at: float | None, now: float, hold_sec: float = CONFIRM_HOLD_SEC) -> bool:
    if armed_at is None:
        return False
    return (now - armed_at) + 1e-9 >= hold_sec


def escape_should_close(confirm: bool) -> bool:
    return not confirm


def show_recover(*, freeze: bool, confirm: bool, recovering: bool) -> bool:
    # Canvas SoT: freeze || confirm || recovering. Retry-on-note is NOT used —
    # a failed recover still blinks sensors, so Recover stays visible via freeze.
    return freeze or confirm or recovering


def is_freeze_snap(snap: dict) -> bool:
    """FREEZE pill only for A/V path — Telnet/UI are context."""
    return any((snap.get(k) or {}).get("tone") == "FAIL" for k in FREEZE_KEYS)


def is_healthy_snap(snap: dict) -> bool:
    if is_freeze_snap(snap):
        return False
    return all((snap.get(k) or {}).get("tone") == "OK" for k in FREEZE_KEYS)


def clock_digits(updated_at: str) -> tuple[str, str]:
    m = re.search(r"(\d{2}):(\d{2})", str(updated_at or ""))
    if not m:
        return "--", "--"
    return m.group(1), m.group(2)


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


def is_stale(updated_at: str, poll_sec: int, now: datetime | None = None, grace: int = STALE_GRACE_SEC) -> bool:
    age = snap_age_sec(updated_at, now)
    if age is None:
        return False
    return age > (poll_sec * 2 + grace)


def note_color(note: str, recovering: bool) -> str:
    n = (note or "").lower()
    if any(w in n for w in ("fail", "failed", "timed out", "timeout", "cannot recover", "skipped", "error")):
        return FAIL
    if recovering or any(w in n for w in ("waiting", "rebooting", "backing up", "recovering", "confirm")):
        return WARN
    if "zapped" in n:
        return OK
    return TEXT_2


def ellipsize(text: str, max_len: int = DETAIL_MAX) -> str:
    s = " ".join((text or "").split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def recover_title(confirm: bool, recovering: bool) -> str:
    if recovering:
        return TITLE_RECOVERING
    if confirm:
        return TITLE_CONFIRM
    return TITLE_RECOVER


def _app_version() -> str:
    try:
        from spidervip._version import __version__

        return __version__
    except Exception:
        return ""


def _hwnd(root: "tk.Tk") -> int:
    wid = int(root.winfo_id())
    try:
        parent = int(ctypes.windll.user32.GetParent(wid))
    except Exception:
        parent = 0
    return parent or wid


def _work_area() -> tuple[int, int, int, int]:
    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    rect = RECT()
    try:
        ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    except Exception:
        return 0, 0, 1280, 720


def _apply_win32_chrome(root: "tk.Tk", width: int, height: int) -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = _hwnd(root)
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        pref = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref)
        )
        # Do not SetWindowRgn: a too-small region clipped the probes so only
        # the clock was visible. Win11 DWM rounding is enough.
    except Exception:
        pass


def _set_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def try_single_instance() -> bool:
    """True if this process owns the overlay mutex (or mutex is unavailable)."""
    if getattr(try_single_instance, "_handle", None):
        return True
    if sys.platform != "win32":
        return True
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if not handle:
            return True
        if ctypes.GetLastError() == ERROR_ALREADY_EXISTS:
            ctypes.windll.kernel32.CloseHandle(handle)
            return False
        try_single_instance._handle = handle  # type: ignore[attr-defined]
        return True
    except Exception:
        return True


def round_rect(cv, x1: float, y1: float, x2: float, y2: float, r: float, **kw):
    r = max(0.0, min(float(r), (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    pts = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
        x1 + r, y1,
    ]
    return cv.create_polygon(pts, smooth=True, splinesteps=12, **kw)


def _empty_item(detail: str = "waiting") -> dict:
    return {"tone": "UNKNOWN", "detail": detail, "blink": False}


def _empty_snap(host: str) -> dict:
    return {
        "updatedAt": "--:--",
        "hostname": "clap4k",
        "host": host,
        "phase": "idle",
        "recoverNote": "",
        "telnet": _empty_item("waiting for first poll"),
        "av": {**_empty_item("no sample"), "play": "-", "vid": "-", "aud": "-"},
        "vdec": _empty_item("no sample"),
        "win": _empty_item("no sample"),
        "adec": _empty_item("no sample"),
        "ui": _empty_item("no sample"),
    }


class _Tooltip:
    def __init__(self, widget, text: str = "") -> None:
        self.widget = widget
        self.text = text
        self._tw = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def set_text(self, text: str) -> None:
        self.text = text or ""

    def _show(self, _e=None) -> None:
        if not self.text or self._tw is not None or tk is None:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            return
        self._tw = tk.Toplevel(self.widget)
        self._tw.wm_overrideredirect(True)
        try:
            self._tw.attributes("-topmost", True)
        except tk.TclError:
            pass
        tk.Label(
            self._tw,
            text=self.text,
            bg=TILE_BG,
            fg=TEXT,
            font=("Segoe UI", 9),
            padx=8,
            pady=4,
            justify="left",
            wraplength=280,
        ).pack()
        self._tw.geometry("+%d+%d" % (x, y))

    def _hide(self, _e=None) -> None:
        if self._tw is not None:
            try:
                self._tw.destroy()
            except tk.TclError:
                pass
            self._tw = None


class FreezeOverlayWin:
    def __init__(
        self,
        *,
        load_prev: Callable[[], dict],
        queue_recover: Callable[[], None],
        wake: threading.Event,
        stop: threading.Event,
        poll_sec: int,
        host: str,
        save_prev: Callable[[dict], None] | None = None,
    ) -> None:
        if tk is None:
            raise RuntimeError("tkinter is required for the freeze widget: %s" % _TK_ERR)
        self._load_prev = load_prev
        self._save_prev = save_prev
        self._queue_recover = queue_recover
        self._wake = wake
        self._stop = stop
        self._poll_sec = poll_sec
        self._host = host
        self._confirm = False
        self._armed_at: float | None = None
        self._confirm_gen = 0
        self._blink_on = True
        self._drag = None
        self._placed = False
        self._focus = ""

        self.root = tk.Tk()
        self.root.title("SpiderVIP Freeze Widget")
        self.root.configure(bg=SHELL_BG)
        self.root.overrideredirect(True)
        try:
            self.root.attributes("-topmost", True)
            if WIN_ALPHA < 1.0:
                self.root.attributes("-alpha", WIN_ALPHA)
        except tk.TclError:
            pass
        self.root.resizable(False, False)

        self._font = ("Segoe UI", 11)
        self._font_b = ("Segoe UI", 11, "bold")
        self._font_s = ("Segoe UI", 9)
        self._font_sb = ("Segoe UI", 10, "bold")
        self._font_xs = ("Segoe UI", 8)

        # Packed layout so reqheight includes probes. A placed shell does not
        # contribute to root size, so SetWindowRgn used to clip to a clock-only card.
        self.root.geometry("%dx%d" % (WIDGET_W, MIN_H))
        self._bg = tk.Canvas(self.root, bg=SHELL_BG, highlightthickness=0, bd=0)
        self._bg.place(x=0, y=0, relwidth=1, relheight=1)

        self.shell = tk.Frame(self.root, bg=SHELL_BG)
        self.shell.pack(fill="both", expand=True, padx=1, pady=1)
        inner = tk.Frame(self.shell, bg=SHELL_BG, padx=SHELL_PAD, pady=SHELL_PAD)
        inner.pack(fill="both", expand=True)
        self._inner = inner

        hdr = tk.Frame(inner, bg=SHELL_BG)
        hdr.pack(fill="x")
        self._dish = tk.Canvas(hdr, width=18, height=18, bg=SHELL_BG, highlightthickness=0, bd=0)
        self._dish.pack(side="left")
        tk.Label(hdr, text="Freeze overlay", fg=TEXT, bg=SHELL_BG, font=self._font_b).pack(
            side="left", padx=(8, 0)
        )
        self._xbtn = tk.Canvas(
            hdr, width=HIT, height=HIT, bg=SHELL_BG, highlightthickness=0, bd=0, takefocus=1
        )
        self._xbtn.pack(side="right")
        self._xbtn.bind("<Button-1>", lambda _e: self._close())
        self._xbtn.bind("<Return>", lambda _e: self._close())
        self._xbtn.bind("<space>", lambda _e: self._close())
        self._xbtn.bind("<FocusIn>", lambda _e: self._set_focus("close"))
        self._xbtn.bind("<FocusOut>", lambda _e: self._set_focus(""))
        self._xbtn.bind("<Enter>", lambda _e: self._draw_close(hover=True))
        self._xbtn.bind("<Leave>", lambda _e: self._draw_close(hover=False))
        self._x_tip = _Tooltip(self._xbtn, "Close")
        self._close_hover = False

        sub = tk.Frame(inner, bg=SHELL_BG)
        sub.pack(fill="x", pady=(2, 0))
        self._net = tk.Canvas(sub, width=16, height=16, bg=SHELL_BG, highlightthickness=0, bd=0)
        self._net.pack(side="left")
        self._host_lbl = tk.Label(sub, text="", fg=TEXT_2, bg=SHELL_BG, font=self._font_s, anchor="w")
        self._host_lbl.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self._clock = tk.Frame(inner, bg=SHELL_BG)
        self._clock.pack(pady=(12, 2))
        self._digits: list[tk.Canvas] = []
        tile_w, tile_h = DIGIT_W + 8, DIGIT_H + 12
        for i in range(4):
            cv = tk.Canvas(
                self._clock, width=tile_w, height=tile_h, bg=SHELL_BG, highlightthickness=0, bd=0
            )
            cv.pack(side="left", padx=3)
            self._digits.append(cv)
            if i == 1:
                colon = tk.Canvas(
                    self._clock, width=12, height=tile_h, bg=SHELL_BG, highlightthickness=0, bd=0
                )
                colon.pack(side="left", padx=2)
                self._colon = colon
        self._clock_cap = tk.Label(
            inner, text=CLOCK_CAPTION, fg=TEXT_3, bg=SHELL_BG, font=self._font_xs
        )
        self._clock_cap.pack()

        meta = tk.Frame(inner, bg=SHELL_BG)
        meta.pack(fill="x", pady=(8, 0))
        self._pill = tk.Canvas(meta, width=78, height=PILL_H, bg=SHELL_BG, highlightthickness=0, bd=0)
        self._pill.pack(side="left")
        self._avline = tk.Label(meta, text="A/V —", fg=TEXT_2, bg=SHELL_BG, font=self._font_s)
        self._avline.pack(side="left", padx=(8, 0))
        ver = _app_version()
        poll_txt = "v%s  poll %ss" % (ver, poll_sec) if ver else "poll %ss" % poll_sec
        self._ver = tk.Label(meta, text=poll_txt, fg=TEXT_3, bg=SHELL_BG, font=self._font_s)
        self._ver.pack(side="right")

        ctrl = tk.Frame(inner, bg=SHELL_BG)
        ctrl.pack(fill="x", pady=(14, 4))
        left = tk.Frame(ctrl, bg=SHELL_BG)
        left.pack(side="left")
        self._av_chip = tk.Canvas(left, width=40, height=40, bg=SHELL_BG, highlightthickness=0, bd=0)
        self._av_chip.pack(side="left", padx=(0, 8))
        self._ui_chip = tk.Canvas(left, width=40, height=40, bg=SHELL_BG, highlightthickness=0, bd=0)
        self._ui_chip.pack(side="left")
        self._av_tip = _Tooltip(self._av_chip, "Audio / video path")
        self._ui_tip = _Tooltip(self._ui_chip, "UI process")
        self._recover = tk.Canvas(
            ctrl, width=64, height=64, bg=SHELL_BG, highlightthickness=0, bd=0, takefocus=1
        )
        self._recover.pack(side="right")
        self._recover.bind("<Button-1>", self._on_recover)
        self._recover.bind("<Return>", self._on_recover)
        self._recover.bind("<space>", self._on_recover)
        self._recover.bind("<FocusIn>", lambda _e: self._set_focus("recover"))
        self._recover.bind("<FocusOut>", lambda _e: self._set_focus(""))
        self._rec_tip = _Tooltip(self._recover, TITLE_RECOVER)

        self._note = tk.Label(
            inner,
            text="",
            fg=TEXT_2,
            bg=SHELL_BG,
            font=self._font_s,
            wraplength=WIDGET_W - 56,
            justify="left",
            anchor="w",
        )

        self._probes_wrap = tk.Frame(inner, bg=SHELL_BG)
        self._probes_wrap.pack(fill="x", pady=(4, 0))
        self._probes_cv = None
        self._probes = tk.Frame(self._probes_wrap, bg=TILE_BG, padx=12, pady=10)
        self._probes.pack(fill="x")
        tk.Label(
            self._probes, text="Probes", fg=TILE_TEXT, bg=TILE_BG, font=self._font_sb, anchor="w"
        ).pack(fill="x", pady=(0, 6))
        self._row_widgets: dict[str, dict] = {}
        for key, label in ROWS:
            row = tk.Frame(self._probes, bg=TILE_BG)
            row.pack(fill="x", pady=3)
            ic = tk.Canvas(row, width=16, height=16, bg=TILE_BG, highlightthickness=0, bd=0)
            ic.pack(side="left", anchor="n", pady=2)
            tk.Label(
                row, text=label, fg=TILE_TEXT, bg=TILE_BG, font=self._font, width=12, anchor="nw"
            ).pack(side="left", padx=(8, 0), anchor="n")
            tone_l = tk.Label(row, text="", fg=TILE_TEXT_3, bg=TILE_BG, font=self._font_sb, width=8, anchor="nw")
            tone_l.pack(side="left", anchor="n")
            det = tk.Label(
                row,
                text="",
                fg=TILE_TEXT_2,
                bg=TILE_BG,
                font=self._font_s,
                anchor="nw",
                justify="left",
                wraplength=WIDGET_W - 200,
            )
            det.pack(side="left", fill="x", expand=True, anchor="n")
            tip = _Tooltip(det, "")
            self._row_widgets[key] = {"icon": ic, "tone": tone_l, "detail": det, "tip": tip}
        tk.Label(
            self._probes,
            text="FREEZE = MSP flow/VPSS dead, avplay STOP, missing vdec/win/adec, or sync STOP with dead path. VidPid 0x1fff alone is WARN.",
            fg=TILE_TEXT_3,
            bg=TILE_BG,
            font=self._font_s,
            wraplength=WIDGET_W - 72,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(8, 0))

        self._drag_handles = (self.root, self._bg, self.shell, inner, hdr, sub, self._clock, meta)
        for w in self._drag_handles:
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)
        self.root.bind("<Escape>", self._on_escape)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Configure>", self._on_root_cfg)

        self._draw_close()
        self._refresh()
        self.root.after(200, self._place_once)
        self.root.after(500, self._tick)

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self._stop.set()
            self._wake.set()

    def _set_focus(self, name: str) -> None:
        self._focus = name
        if name == "close":
            self._draw_close(hover=self._close_hover)
        self._refresh()

    def _persist_geom(self) -> None:
        if self._save_prev is None:
            return
        try:
            prev = self._load_prev() or {}
            prev["overlayGeom"] = {"x": int(self.root.winfo_x()), "y": int(self.root.winfo_y())}
            self._save_prev(prev)
        except Exception:
            pass

    def _close(self) -> None:
        self._persist_geom()
        self._stop.set()
        self._wake.set()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _cancel_confirm(self) -> None:
        self._confirm = False
        self._armed_at = None
        self._confirm_gen += 1
        self._refresh()

    def _on_escape(self, _e=None) -> None:
        if self._confirm:
            self._cancel_confirm()
            return
        self._close()

    def _start_drag(self, evt) -> None:
        skip = (self._recover, self._xbtn, self._av_chip, self._ui_chip, self._probes)
        if evt.widget in skip:
            return
        w = evt.widget
        try:
            while w is not None:
                if w in (self._probes, self._recover, self._xbtn):
                    return
                w = w.master
        except Exception:
            pass
        self._drag = (evt.x_root - self.root.winfo_x(), evt.y_root - self.root.winfo_y())

    def _do_drag(self, evt) -> None:
        if not self._drag:
            return
        self.root.geometry("+%d+%d" % (evt.x_root - self._drag[0], evt.y_root - self._drag[1]))

    def _content_size(self) -> tuple[int, int]:
        self.root.update_idletasks()
        inner_h = int(self._inner.winfo_reqheight()) if hasattr(self, "_inner") else 0
        h = max(MIN_H, inner_h + 28)
        return WIDGET_W, h

    def _place_once(self) -> None:
        w, h = self._content_size()
        left, top, right, bottom = _work_area()
        x = right - w - 18
        y = bottom - h - 18
        prev = self._load_prev() or {}
        geom = prev.get("overlayGeom") or {}
        try:
            px, py = int(geom.get("x")), int(geom.get("y"))
            if left <= px <= right - 80 and top <= py <= bottom - 80:
                x, y = px, py
        except (TypeError, ValueError):
            pass
        if x < left:
            x = left + 8
        if y < top:
            y = top + 8
        if x + w > right:
            x = max(left + 8, right - w - 8)
        if y + h > bottom:
            y = max(top + 8, bottom - h - 8)
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.root.update_idletasks()
        _apply_win32_chrome(self.root, w, h)
        self._redraw_glass(w, h)
        self._placed = True

    def _on_root_cfg(self, _e=None) -> None:
        if not self._placed:
            return
        try:
            self._redraw_glass(self.root.winfo_width(), self.root.winfo_height())
        except tk.TclError:
            pass

    def _redraw_glass(self, w: int, h: int) -> None:
        cv = self._bg
        cv.delete("glass")
        if w < 8 or h < 8:
            return
        # Canvas OverlayShell: fill.tertiary + 1px stroke.secondary, radius 36.
        round_rect(
            cv, 0.5, 0.5, w - 0.5, h - 0.5, CORNER_R,
            fill=SHELL_BG, outline=STROKE, width=1, tags="glass",
        )

    def _fit_height(self) -> None:
        if not self._placed:
            return
        try:
            w, h = self._content_size()
            if w == self.root.winfo_width() and abs(h - self.root.winfo_height()) < 4:
                return
            self.root.geometry("%dx%d+%d+%d" % (w, h, self.root.winfo_x(), self.root.winfo_y()))
            _apply_win32_chrome(self.root, w, h)
            self._redraw_glass(w, h)
        except tk.TclError:
            pass

    def _tick(self) -> None:
        if self._stop.is_set():
            self._close()
            return
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        if self._confirm and confirm_expired(self._armed_at, time.monotonic()):
            self._cancel_confirm()
        self._blink_on = not self._blink_on
        self._refresh()
        self.root.after(500, self._tick)

    def _snapshot(self) -> tuple[dict, dict]:
        prev = self._load_prev() or {}
        snap = prev.get("snapshot") or _empty_snap(self._host)
        return prev, snap

    def _recovering(self, prev: dict, snap: dict) -> bool:
        try:
            nonce = int(prev.get("recoverNonce") or 0)
            handled = int(prev.get("handledRecoverNonce") or 0)
        except (TypeError, ValueError):
            nonce = handled = 0
        return snap.get("phase") == "recovering" or nonce > handled

    def _paint(self, color: str, blink: bool, bg: str) -> str:
        if blink and not self._blink_on:
            return _hex8_on(bg, color + "2E")
        return color

    def _refresh(self) -> None:
        prev, snap = self._snapshot()
        recovering = self._recovering(prev, snap)
        if recovering:
            self._confirm = False
            self._armed_at = None

        freeze = is_freeze_snap(snap)
        healthy = is_healthy_snap(snap)
        stale = is_stale(str(snap.get("updatedAt") or ""), self._poll_sec)
        dish_c = OK if healthy and not stale else (FAIL if freeze else TEXT)
        self._draw_dish(self._dish, self._paint(dish_c, freeze, SHELL_BG), SHELL_BG)

        host = snap.get("host") or self._host
        hn = snap.get("hostname") or "clap4k"
        self._host_lbl.configure(text="%s · %s" % (hn, host))
        tel = snap.get("telnet") or {}
        self._draw_status_icon(
            self._net, "telnet", _tone_color(tel.get("tone") or "UNKNOWN"), SHELL_BG
        )

        updated = str(snap.get("updatedAt") or "")
        hh, mm = clock_digits(updated)
        for i, ch in enumerate((hh[0], hh[1], mm[0], mm[1])):
            self._draw_digit(self._digits[i], ch)
        self._colon.delete("all")
        self._colon.create_oval(3, 24, 9, 30, fill=TEXT, outline="")
        self._colon.create_oval(3, 48, 9, 54, fill=TEXT, outline="")
        age = snap_age_sec(updated)
        cap = CLOCK_CAPTION
        if age is not None:
            cap = "Last poll %ds ago · this PC (not box time)" % max(0, int(age))
            if stale:
                cap = "STALE · " + cap
        self._clock_cap.configure(text=cap, fg=WARN if stale else TEXT_3)

        av = snap.get("av") or {}
        play = av.get("play") or "—"
        if healthy and not stale:
            pill, pill_fg = "LIVE", OK
        elif freeze:
            pill, pill_fg = "FREEZE", FAIL
        elif stale:
            pill, pill_fg = "STALE", WARN
        else:
            pill, pill_fg = (av.get("play") or "WAIT"), WARN
        self._draw_pill(pill, pill_fg)
        self._avline.configure(text="A/V %s" % play)

        self._draw_chip(
            self._av_chip, "av", _tone_color(av.get("tone") or "UNKNOWN"), av.get("blink", False)
        )
        ui = snap.get("ui") or {}
        self._draw_chip(
            self._ui_chip, "ui", _tone_color(ui.get("tone") or "UNKNOWN"), ui.get("blink", False)
        )

        visible = show_recover(freeze=freeze, confirm=self._confirm, recovering=recovering)
        self._draw_recover(visible, recovering)
        self._rec_tip.set_text(recover_title(self._confirm, recovering) if visible else "")
        self._recover.configure(
            cursor="hand2" if visible and not recovering else "arrow",
            takefocus=1 if visible else 0,
        )

        note = (snap.get("recoverNote") or "").strip()
        if recovering and not note:
            note = "Recovering…"
        if self._confirm and not recovering:
            note = NOTE_CONFIRM
        if note:
            self._note.configure(text=note, fg=note_color(note, recovering))
            if not self._note.winfo_ismapped():
                self._note.pack(fill="x", pady=(0, 6), before=self._probes_wrap)
        else:
            self._note.configure(text="")
            self._note.pack_forget()

        for key, _label in ROWS:
            item = snap.get(key) or _empty_item()
            color = _tone_color(item.get("tone") or "UNKNOWN")
            blink = bool(item.get("blink"))
            paint = self._paint(color, blink, TILE_BG)
            w = self._row_widgets[key]
            self._draw_status_icon(w["icon"], key, paint, TILE_BG)
            w["tone"].configure(text=item.get("tone") or "UNKNOWN", fg=paint)
            full = item.get("detail") or ""
            w["detail"].configure(text=full or "—", fg=TILE_TEXT_2)
            w["tip"].set_text(full)
        self._fit_height()

    def _on_recover(self, _evt=None) -> str | None:
        prev, snap = self._snapshot()
        if self._recovering(prev, snap):
            return "break"
        freeze = is_freeze_snap(snap)
        if not show_recover(freeze=freeze, confirm=self._confirm, recovering=False):
            return "break"
        now = time.monotonic()
        if not self._confirm:
            self._confirm = True
            self._armed_at = now
            self._confirm_gen += 1
            gen = self._confirm_gen
            try:
                self.root.after(int(CONFIRM_HOLD_SEC * 1000), lambda: self._expire_confirm(gen))
            except tk.TclError:
                pass
            self._refresh()
            return "break"
        if not confirm_ready(self._armed_at, now):
            return "break"
        self._confirm = False
        self._armed_at = None
        self._queue_recover()
        self._wake.set()
        self._refresh()
        return "break"

    def _expire_confirm(self, gen: int) -> None:
        if self._confirm and gen == self._confirm_gen:
            self._cancel_confirm()

    def _draw_digit(self, cv: "tk.Canvas", ch: str) -> None:
        cv.delete("all")
        w, h = int(cv["width"]), int(cv["height"])
        round_rect(cv, 0, 0, w, h, TILE_R, fill=TILE_BG, outline="")
        grid = DOT.get(ch, DOT["-"])
        cell, gap, pad = DIGIT_CELL, DIGIT_GAP, DIGIT_PAD
        r = cell / 2 - 0.4
        ox = (w - (pad * 2 + 5 * cell + 4 * gap)) / 2
        oy = (h - (pad * 2 + 7 * cell + 6 * gap)) / 2
        for y, row in enumerate(grid):
            for x, bit in enumerate(row):
                cx = ox + pad + cell / 2 + x * (cell + gap)
                cy = oy + pad + cell / 2 + y * (cell + gap)
                fill = DIGIT_ON if bit else DIGIT_OFF
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline="")

    def _draw_pill(self, text: str, fg: str) -> None:
        cv = self._pill
        cv.delete("all")
        w, h = int(cv["width"]), int(cv["height"])
        round_rect(cv, 1, 1, w - 1, h - 1, h / 2, fill=TILE_BG, outline=STROKE, width=1)
        cv.create_text(w / 2, h / 2, text=text, fill=fg, font=self._font_xs)

    def _draw_close(self, hover: bool = False) -> None:
        self._close_hover = hover
        cv = self._xbtn
        cv.delete("all")
        color = TEXT if hover or self._focus == "close" else TEXT_2
        if self._focus == "close":
            round_rect(cv, 4, 4, HIT - 4, HIT - 4, 10, fill=SHELL_BG, outline=FOCUS, width=1)
        cv.create_line(16, 16, HIT - 16, HIT - 16, fill=color, width=1.6, capstyle="round")
        cv.create_line(HIT - 16, 16, 16, HIT - 16, fill=color, width=1.6, capstyle="round")

    def _draw_dish(self, cv: "tk.Canvas", color: str, bg: str) -> None:
        cv.delete("all")
        cv.configure(bg=bg)
        paint_dish(cv, color)

    def _draw_status_icon(self, cv: "tk.Canvas", kind: str, color: str, bg: str) -> None:
        cv.delete("all")
        cv.configure(bg=bg)
        paint_status(cv, kind, color)

    def _draw_chip(self, cv: "tk.Canvas", kind: str, color: str, blink: bool) -> None:
        cv.delete("all")
        paint = self._paint(color, blink, TILE_BG)
        cv.create_oval(2, 2, 38, 38, outline=STROKE_HI, width=1, fill=TILE_BG)
        inner = tk.Canvas(cv, width=22, height=22, bg=TILE_BG, highlightthickness=0, bd=0)
        cv.create_window(20, 20, window=inner)
        paint_status(inner, kind, paint)

    def _draw_recover(self, show: bool, recovering: bool) -> None:
        cv = self._recover
        cv.delete("all")
        focused = self._focus == "recover"
        if not show:
            cv.create_oval(2, 2, 62, 62, outline=STROKE_LO, width=1, fill=SHELL_BG)
            inner = tk.Canvas(cv, width=22, height=22, bg=SHELL_BG, highlightthickness=0, bd=0)
            cv.create_window(32, 32, window=inner)
            paint_dish(inner, OK)
            return
        cv.create_oval(2, 2, 62, 62, outline=FOCUS if focused else STROKE_HI, width=1.5 if focused else 1, fill=TILE_BG)
        if recovering:
            cv.create_text(32, 28, text="…", fill=TEXT, font=self._font_b)
            cv.create_text(32, 44, text="wait", fill=WARN, font=self._font_xs)
            return
        if self._confirm:
            cv.create_text(32, 26, text="OK", fill=TEXT, font=self._font_sb)
            cv.create_text(32, 42, text="reboot", fill=WARN, font=self._font_xs)
            return
        inner = tk.Canvas(cv, width=20, height=20, bg=TILE_BG, highlightthickness=0, bd=0)
        cv.create_window(32, 32, window=inner)
        paint_recover(inner, TEXT)


def run_ui(
    poll_worker=None,
    *,
    load_prev=None,
    save_prev=None,
    queue_recover=None,
    poll_sec=None,
    host=None,
) -> None:
    """Start the native widget. poll_worker is freeze_overlay.loop_ui."""
    if tk is None:
        print("tkinter is required for the freeze widget: %s" % _TK_ERR, flush=True)
        raise SystemExit(1)
    _set_dpi()
    if not try_single_instance():
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                "Freeze overlay is already running. Close the existing widget first.",
                "SpiderVIP Freeze Widget",
                0x00040000,
            )
        except Exception:
            pass
        print("Freeze overlay is already running. Close the existing widget first.", flush=True)
        raise SystemExit(2)

    if load_prev is None:
        import freeze_overlay as fo  # noqa: WPS433

        load_prev = fo._load_prev
        save_prev = fo._save_prev
        queue_recover = fo._queue_recover
        poll_sec = fo.POLL_SEC
        host = fo.HOST

    stop = threading.Event()
    wake = threading.Event()
    if poll_worker is not None:
        threading.Thread(
            target=poll_worker,
            kwargs={"stop_event": stop, "wake_event": wake},
            name="freeze-poll",
            daemon=True,
        ).start()
        print("Freeze overlay native widget (Tk)  poll %ss" % poll_sec, flush=True)

    ui = FreezeOverlayWin(
        load_prev=load_prev,
        save_prev=save_prev,
        queue_recover=queue_recover,
        wake=wake,
        stop=stop,
        poll_sec=int(poll_sec or 12),
        host=str(host or ""),
    )
    try:
        ui.run()
    finally:
        stop.set()
        wake.set()


if __name__ == "__main__":
    import freeze_overlay as _fo

    run_ui(
        poll_worker=_fo.loop_ui,
        load_prev=_fo._load_prev,
        save_prev=_fo._save_prev,
        queue_recover=_fo._queue_recover,
        poll_sec=_fo.POLL_SEC,
        host=_fo.HOST,
    )
