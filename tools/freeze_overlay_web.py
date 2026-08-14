#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Native Windows freeze overlay hosted in Edge WebView2 (pywebview).

Renders tools/freeze_overlay.html — the OverlayShell twin of
freeze-status.canvas.tsx. No browser window, no HTTP server.

Chrome matches the Tk widget: Win11 DWM rounded corners (DWMWCP_ROUND)
and native caption drag (WM_NCLBUTTONDOWN / HTCAPTION). pywebview's JS
drag mixes clientX with screenX and breaks on DPI scaling.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from typing import Callable

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MUTEX_NAME = "Local\\SpiderVIPFreezeOverlay.mutex"
ERROR_ALREADY_EXISTS = 183
HTML_PATH = os.path.join(_HERE, "freeze_overlay.html")
BG_EDITOR = "#181818"
# fill.tertiary #E4E4E411 composited onto editor — form/WebView2 must match
# or Win11 DWM top corners show black #181818.
SHELL_BG = "#262626"
WIN_W = 360
# Layout budget (logical CSS px). Matches OverlayShell: header/clock/ctrl + N probe rows.
_CHROME_H = 470  # title..recover + note + probes chrome/hint/pad
_PROBE_ROW_H = 30  # .probe min-height 26 + gap 4
_CARD_PAD = 44  # .card padding 22*2


def _probe_count() -> int:
    try:
        from freeze_overlay import SENSOR_KEYS

        return len(SENSOR_KEYS)
    except Exception:
        return 13


def _content_height(n: int | None = None) -> int:
    """Deterministic window height for current probe count — no viewport inflation."""
    rows = _probe_count() if n is None else int(n)
    return _CHROME_H + _CARD_PAD + rows * _PROBE_ROW_H


WIN_H = _content_height()  # ~904 for 13 rows
MIN_H = _content_height(6)  # never smaller than the old 6-row card
MAX_H = 1200


def _work_area_h() -> int:
    if sys.platform != "win32":
        return MAX_H
    try:

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        rect = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
            return max(MIN_H, int(rect.bottom - rect.top) - 48)
    except Exception:
        pass
    return MAX_H
# DWMWA_WINDOW_CORNER_PREFERENCE / DWMWCP_ROUND — same as freeze_overlay_win.
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2
WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

try:
    import webview
except Exception as exc:  # pragma: no cover - optional extra
    webview = None  # type: ignore[assignment]
    _WV_ERR: BaseException | None = exc
else:
    _WV_ERR = None


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


def _app_version() -> str:
    try:
        from spidervip._version import __version__

        return __version__
    except Exception:
        return ""


def _stamp_html(raw: str) -> str:
    try:
        from spidervip.app_meta import stamp_html

        return stamp_html(raw)
    except Exception:
        ver = _app_version()
        if ver:
            return raw.replace("__SPIDERVIP_VERSION__", ver)
        return raw


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
    except Exception:
        pass


def _form_hwnd(form) -> int:
    handle = form.Handle
    try:
        return int(handle.ToInt64())
    except Exception:
        return int(handle.ToInt32()) & 0xFFFFFFFF


def _ui_call(form, fn) -> None:
    """Run fn on the WinForms UI thread when possible."""
    try:
        from System import Action

        if getattr(form, "InvokeRequired", False):
            form.BeginInvoke(Action(fn))
            return
    except Exception:
        pass
    fn()


def _apply_win32_chrome(window) -> None:
    """Match Tk overlay: Win11 rounded corners, no taskbar chrome."""
    if sys.platform != "win32" or window is None:
        return
    form = getattr(window, "native", None)
    if form is None:
        return

    def _apply() -> None:
        try:
            hwnd = _form_hwnd(form)
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            pref = ctypes.c_int(DWMWCP_ROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(pref),
                ctypes.sizeof(pref),
            )
            user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
            )
            try:
                from System.Drawing import ColorTranslator

                color = ColorTranslator.FromHtml(SHELL_BG)
                form.BackColor = color
                browser = getattr(form, "browser", None)
                wv = getattr(form, "webview", None) or getattr(browser, "webview", None)
                if wv is not None:
                    wv.DefaultBackgroundColor = color
            except Exception:
                pass
        except Exception:
            pass

    _ui_call(form, _apply)


def _schedule_chrome(window) -> None:
    _apply_win32_chrome(window)

    def _later(delay: float) -> None:
        def _run() -> None:
            time.sleep(delay)
            _apply_win32_chrome(window)

        threading.Thread(target=_run, name="freeze-chrome", daemon=True).start()

    # WebView2 init can reset DWM prefs; re-apply like Tk does after map.
    _later(0.05)
    _later(0.35)
    _later(1.0)


def _load_html() -> str:
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        return _stamp_html(f.read())


class OverlayApi:
    def __init__(
        self,
        load_prev: Callable[[], dict],
        queue_recover: Callable[[], None],
        wake: threading.Event,
        stop: threading.Event,
        poll_sec: int,
    ) -> None:
        self._load_prev = load_prev
        self._queue_recover = queue_recover
        self._wake = wake
        self._stop = stop
        self._poll_sec = poll_sec
        self._window = None
        self._fitted = 0

    def snapshot(self) -> dict:
        prev = self._load_prev() or {}
        return {
            "snapshot": prev.get("snapshot") or {},
            "recoverNonce": int(prev.get("recoverNonce") or 0),
            "version": _app_version(),
            "pollSec": self._poll_sec,
        }

    def recover(self) -> bool:
        self._queue_recover()
        self._wake.set()
        return True

    def fit_height(self, height: int = 0) -> bool:
        """Size hwnd to probe content. Ignores inflated WebView2 viewport heights."""
        target = _content_height()
        try:
            if isinstance(height, (list, tuple)):
                height = height[0] if height else 0
            measured = int(round(float(height or 0)))
        except Exception:
            measured = 0
        # Trust JS only when it is near the design budget; otherwise use formula.
        if measured and abs(measured - target) <= 80:
            h = measured
        else:
            h = target
        h = max(MIN_H, min(min(MAX_H, _work_area_h()), h))
        win = self._window
        if win is None:
            return False
        if abs(self._fitted - h) < 2:
            return True
        self._fitted = h
        try:
            win.resize(WIN_W, h)
        except Exception:
            return False
        _apply_win32_chrome(win)
        return True

    def start_drag(self) -> bool:
        """Native caption drag — same feel as the Tk widget, DPI-correct."""
        win = self._window
        form = getattr(win, "native", None) if win is not None else None
        if form is None:
            return False

        def _ncdown() -> None:
            try:
                hwnd = _form_hwnd(form)
                ctypes.windll.user32.ReleaseCapture()
                ctypes.windll.user32.PostMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)
            except Exception:
                pass

        _ui_call(form, _ncdown)
        return True

    def close(self) -> bool:
        self._stop.set()
        self._wake.set()
        win = self._window
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        return True


def _push_snapshots(api: OverlayApi, stop: threading.Event) -> None:
    last = ""
    while not stop.is_set():
        win = api._window
        if win is not None:
            try:
                payload = api.snapshot()
                blob = json.dumps(payload, ensure_ascii=True)
                if blob != last:
                    last = blob
                    win.evaluate_js("applySnapshot(%s)" % blob)
            except Exception:
                pass
        if stop.wait(0.4):
            break


def run_ui(
    poll_worker=None,
    *,
    load_prev=None,
    save_prev=None,
    queue_recover=None,
    poll_sec=None,
    host=None,
) -> None:
    """Start the WebView2 freeze widget. poll_worker is freeze_overlay.loop_ui."""
    if webview is None:
        raise RuntimeError(
            "pywebview is required for the freeze widget: %s. "
            'Install with: python -m pip install "pywebview>=5"'
            % (_WV_ERR,)
        )
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

    _set_dpi()
    stop = threading.Event()
    wake = threading.Event()
    poll_sec = int(poll_sec or 12)
    api = OverlayApi(load_prev, queue_recover, wake, stop, poll_sec)
    html = _load_html()
    window = webview.create_window(
        "SpiderVIP Freeze Widget",
        html=html,
        js_api=api,
        width=WIN_W,
        height=WIN_H,
        x=48,
        y=48,
        resizable=False,
        frameless=True,
        on_top=True,
        easy_drag=False,
        shadow=False,
        background_color=SHELL_BG,
        text_select=False,
    )
    if window is None:
        raise RuntimeError("webview.create_window returned None")
    api._window = window

    def on_ready():
        _schedule_chrome(window)
        api.fit_height(0)  # apply design-budget height immediately
        if poll_worker is not None:
            threading.Thread(
                target=poll_worker,
                kwargs={"stop_event": stop, "wake_event": wake},
                name="freeze-poll",
                daemon=True,
            ).start()
            print("Freeze overlay native widget (WebView2)  poll %ss" % poll_sec, flush=True)
        threading.Thread(
            target=_push_snapshots,
            args=(api, stop),
            name="freeze-push",
            daemon=True,
        ).start()

    try:
        try:
            window.events.loaded += lambda: _apply_win32_chrome(window)
            window.events.shown += lambda: _apply_win32_chrome(window)
        except Exception:
            pass
        kwargs = {"func": on_ready, "debug": False, "http_server": False}
        if sys.platform == "win32":
            kwargs["gui"] = "edgechromium"
        webview.start(**kwargs)
    except Exception as exc:
        stop.set()
        wake.set()
        print("WebView2 overlay failed to start: %s" % exc, flush=True)
        raise
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
