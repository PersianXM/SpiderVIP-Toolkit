#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canvas SVG icons, drawn on Tk with the same path geometry as freeze-status.canvas.tsx."""
from __future__ import annotations

import math
from typing import Iterable

# viewBox 24 dish / recover; viewBox 16 status icons — same d= as the canvas SVGs.


def _cubic(p0, p1, p2, p3, n: int = 24) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(n + 1):
        t = i / n
        u = 1.0 - t
        x = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0]
        y = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]
        pts.append((x, y))
    return pts


def _arc_points(
    x1: float,
    y1: float,
    rx: float,
    ry: float,
    phi_deg: float,
    large: int,
    sweep: int,
    x2: float,
    y2: float,
    n: int = 28,
) -> list[tuple[float, float]]:
    """SVG elliptical arc (endpoint param) → polyline. W3C implnote."""
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-6 or ry < 1e-6 or (abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9):
        return [(x1, y1), (x2, y2)]
    phi = math.radians(phi_deg)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cos_p * dx + sin_p * dy
    y1p = -sin_p * dx + cos_p * dy
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den))
    if large == sweep:
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = coef * -ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2.0

    def _ang(ux: float, uy: float, vx: float, vy: float) -> float:
        sign = 1.0 if ux * vy - uy * vx >= 0 else -1.0
        dot = ux * vx + uy * vy
        nrm = math.hypot(ux, uy) * math.hypot(vx, vy)
        if nrm < 1e-12:
            return 0.0
        return sign * math.acos(max(-1.0, min(1.0, dot / nrm)))

    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    t1 = _ang(1.0, 0.0, ux, uy)
    dt = _ang(ux, uy, vx, vy)
    if sweep == 0 and dt > 0:
        dt -= 2 * math.pi
    elif sweep == 1 and dt < 0:
        dt += 2 * math.pi
    pts: list[tuple[float, float]] = []
    for i in range(n + 1):
        t = t1 + dt * i / n
        x = cos_p * rx * math.cos(t) - sin_p * ry * math.sin(t) + cx
        y = sin_p * rx * math.cos(t) + cos_p * ry * math.sin(t) + cy
        pts.append((x, y))
    return pts


def _xf(pt: tuple[float, float], scale: float, ox: float, oy: float) -> tuple[float, float]:
    return ox + pt[0] * scale, oy + pt[1] * scale


def _stroke(cv, pts: Iterable[tuple[float, float]], color: str, width: float, scale: float, ox: float, oy: float) -> None:
    seq = [_xf(p, scale, ox, oy) for p in pts]
    if len(seq) < 2:
        return
    flat: list[float] = []
    for x, y in seq:
        flat.extend((x, y))
    cv.create_line(
        *flat,
        fill=color,
        width=max(1.05, width),
        capstyle="round",
        joinstyle="round",
        smooth=False,
    )


def _fill_poly(cv, pts: Iterable[tuple[float, float]], color: str, scale: float, ox: float, oy: float) -> None:
    seq = [_xf(p, scale, ox, oy) for p in pts]
    if len(seq) < 3:
        return
    flat: list[float] = []
    for x, y in seq:
        flat.extend((x, y))
    cv.create_polygon(*flat, fill=color, outline="", smooth=True, splinesteps=8)


def _round_rect(cv, x: float, y: float, w: float, h: float, r: float, color: str, sw: float, scale: float, ox: float, oy: float) -> None:
    x1, y1 = _xf((x, y), scale, ox, oy)
    x2, y2 = _xf((x + w, y + h), scale, ox, oy)
    rr = r * scale
    rr = max(0.0, min(rr, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    pts = [
        x1 + rr, y1,
        x2 - rr, y1,
        x2, y1,
        x2, y1 + rr,
        x2, y2 - rr,
        x2, y2,
        x2 - rr, y2,
        x1 + rr, y2,
        x1, y2,
        x1, y2 - rr,
        x1, y1 + rr,
        x1, y1,
        x1 + rr, y1,
    ]
    cv.create_polygon(*pts, smooth=True, splinesteps=16, fill="", outline=color, width=max(1.05, sw))


def _circle_stroke(cv, cx: float, cy: float, r: float, color: str, sw: float, scale: float, ox: float, oy: float) -> None:
    x, y = _xf((cx, cy), scale, ox, oy)
    rr = r * scale
    cv.create_oval(x - rr, y - rr, x + rr, y + rr, outline=color, width=max(1.05, sw), fill="")


def _circle_fill(cv, cx: float, cy: float, r: float, color: str, scale: float, ox: float, oy: float) -> None:
    x, y = _xf((cx, cy), scale, ox, oy)
    rr = r * scale
    cv.create_oval(x - rr, y - rr, x + rr, y + rr, fill=color, outline="")


def _origin(cv, view: float) -> tuple[float, float, float]:
    w = float(cv.winfo_reqwidth() or int(cv["width"]))
    h = float(cv.winfo_reqheight() or int(cv["height"]))
    scale = min(w, h) / view
    ox = (w - view * scale) / 2.0
    oy = (h - view * scale) / 2.0
    return scale, ox, oy


def _sw(base: float, scale: float) -> float:
    return max(1.1, base * scale)


def paint_dish(cv, color: str) -> None:
    """DishIcon viewBox 0 0 24 24."""
    s, ox, oy = _origin(cv, 24.0)
    sw = _sw(1.7, s)
    bowl = _cubic((3.5, 15.5), (7.7, 21.7), (16.3, 21.7), (20.5, 15.5), 28)
    _stroke(cv, bowl, color, sw, s, ox, oy)
    _stroke(cv, ((13.5, 10.5), (18.0, 5.5)), color, sw, s, ox, oy)
    _circle_fill(cv, 18.6, 5.2, 1.7, color, s, ox, oy)
    _stroke(cv, ((7.0, 20.5), (17.0, 20.5)), color, sw, s, ox, oy)


def paint_telnet(cv, color: str) -> None:
    s, ox, oy = _origin(cv, 16.0)
    sw = _sw(1.4, s)
    _circle_stroke(cv, 4.0, 8.0, 2.1, color, sw, s, ox, oy)
    _circle_stroke(cv, 12.0, 8.0, 2.1, color, sw, s, ox, oy)
    _stroke(cv, ((6.2, 8.0), (9.8, 8.0)), color, sw, s, ox, oy)


def paint_av(cv, color: str) -> None:
    s, ox, oy = _origin(cv, 16.0)
    sw = _sw(1.4, s)
    _stroke(cv, ((3.5, 3.5), (10.0, 3.5), (10.0, 12.5), (3.5, 12.5), (3.5, 3.5)), color, sw, s, ox, oy)
    _fill_poly(cv, ((6.0, 6.2), (8.6, 8.0), (6.0, 9.8)), color, s, ox, oy)
    wave1 = _cubic((11.5, 6.2), (12.4, 6.7), (12.4, 8.3), (11.5, 8.8), 16)
    wave2 = _cubic((13.0, 5.0), (14.5, 5.9), (14.5, 9.1), (13.0, 10.0), 18)
    _stroke(cv, wave1, color, sw, s, ox, oy)
    _stroke(cv, wave2, color, sw, s, ox, oy)


def paint_ui(cv, color: str) -> None:
    s, ox, oy = _origin(cv, 16.0)
    sw = _sw(1.4, s)
    _round_rect(cv, 2.5, 3.5, 11.0, 8.0, 1.4, color, sw, s, ox, oy)
    _stroke(cv, ((6.0, 13.5), (10.0, 13.5)), color, sw, s, ox, oy)


def paint_load(cv, color: str) -> None:
    s, ox, oy = _origin(cv, 16.0)
    sw = _sw(1.6, s)
    _stroke(cv, ((3.5, 11.5), (3.5, 8.0)), color, sw, s, ox, oy)
    _stroke(cv, ((8.0, 12.5), (8.0, 4.5)), color, sw, s, ox, oy)
    _stroke(cv, ((12.5, 11.5), (12.5, 7.0)), color, sw, s, ox, oy)


def paint_vdec(cv, color: str) -> None:
    s, ox, oy = _origin(cv, 16.0)
    sw = _sw(1.4, s)
    pin = _sw(1.3, s)
    _round_rect(cv, 4.0, 4.0, 8.0, 8.0, 1.2, color, sw, s, ox, oy)
    for a, b in (
        ((6.0, 2.5), (6.0, 4.0)),
        ((10.0, 2.5), (10.0, 4.0)),
        ((6.0, 12.0), (6.0, 13.5)),
        ((10.0, 12.0), (10.0, 13.5)),
        ((2.5, 6.0), (4.0, 6.0)),
        ((2.5, 10.0), (4.0, 10.0)),
        ((12.0, 6.0), (13.5, 6.0)),
        ((12.0, 10.0), (13.5, 10.0)),
    ):
        _stroke(cv, (a, b), color, pin, s, ox, oy)


def paint_recover(cv, color: str) -> None:
    """Restart glyph, viewBox 0 0 24 24, 20px in canvas Recover button."""
    s, ox, oy = _origin(cv, 24.0)
    sw = _sw(1.8, s)
    for a, b in (
        ((12.0, 5.0), (12.0, 8.0)),
        ((12.0, 16.0), (12.0, 19.0)),
        ((5.0, 12.0), (8.0, 12.0)),
        ((16.0, 12.0), (19.0, 12.0)),
    ):
        _stroke(cv, (a, b), color, sw, s, ox, oy)
    arc = _arc_points(12.0, 8.0, 4.0, 4.0, 0.0, 1, 1, 8.5, 10.0, 32)
    _stroke(cv, arc, color, sw, s, ox, oy)


def paint_win(cv, color: str) -> None:
    """Video window win0100 — rounded screen."""
    s, ox, oy = _origin(cv, 16.0)
    sw = _sw(1.4, s)
    _round_rect(cv, 2.5, 3.5, 11.0, 8.0, 1.2, color, sw, s, ox, oy)
    _stroke(cv, ((5.0, 13.2), (11.0, 13.2)), color, sw, s, ox, oy)


def paint_adec(cv, color: str) -> None:
    """Audio decoder — speaker + waves (canvas AvIcon waves without the screen)."""
    s, ox, oy = _origin(cv, 16.0)
    sw = _sw(1.4, s)
    _fill_poly(cv, ((3.5, 6.2), (6.2, 6.2), (9.0, 4.0), (9.0, 12.0), (6.2, 9.8), (3.5, 9.8)), color, s, ox, oy)
    wave1 = _cubic((11.0, 6.2), (11.9, 6.7), (11.9, 8.3), (11.0, 8.8), 16)
    wave2 = _cubic((12.6, 5.0), (14.1, 5.9), (14.1, 9.1), (12.6, 10.0), 18)
    _stroke(cv, wave1, color, sw, s, ox, oy)
    _stroke(cv, wave2, color, sw, s, ox, oy)


STATUS = {
    "telnet": paint_telnet,
    "av": paint_av,
    "stat": paint_vdec,
    "vpss": paint_vdec,
    "vdec": paint_vdec,
    "win": paint_win,
    "adec": paint_adec,
    "sync": paint_av,
    "demux": paint_telnet,
    "frontend": paint_telnet,
    "hdmi": paint_ui,
    "stall": paint_vdec,
    "ui": paint_ui,
}


def paint_status(cv, kind: str, color: str) -> None:
    STATUS.get(kind, paint_vdec)(cv, color)
