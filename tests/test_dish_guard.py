"""Tests for the on-box dish-drive key guard (decision logic; no receiver needed)."""

from __future__ import annotations

import ast
from pathlib import Path

from spidervip.patches.dish_guard import dish_guard as dg

SRC = Path(dg.__file__)
# Real kernel lines from the receiver (2026-11-13).
DETACH = b"4,5796,391212833,-;hi_dvb_set_source [dmx: 0, tuner: -1, isvtuner: 0]\n"
ATTACH = b"4,5811,391849323,-;hi_dvb_set_source [dmx: 0, tuner: 0, isvtuner: 0]\n"
GADGET = b"7,2971,188621719,-;service gadget: non-core control req23.03 v0000 i0000 l516\n"
TSREAD = b"4,100,1,-;gservice_ts_thread:370: read 65424 bytes\n"


def run(events, until=None, step=0.05):
    """Feed ``(time, line)`` events with ticks in between; return ``[(time, action...)]``."""

    g = dg.Guard()
    out = []
    events = sorted(events, key=lambda e: e[0])
    end = until if until is not None else (events[-1][0] if events else 0.0)
    t, i = 0.0, 0
    while t <= end + 1e-9:
        while i < len(events) and events[i][0] <= t + 1e-9:
            out += [(round(t, 2),) + a for a in g.feed(events[i][1], events[i][0])]
            i += 1
        out += [(round(t, 2),) + a for a in g.tick(t)]
        t += step
    return g, out


def storm(start, end, rate=87.0):
    n = int((end - start) * rate)
    return [(start + k / rate, GADGET) for k in range(n)]


def quiet(start, end, rate=13.0):
    n = int((end - start) * rate)
    return [(start + k / rate, GADGET) for k in range(n)]


def test_drive_holds_the_remote_until_the_tuner_is_back():
    # Measured: detach, ~87 requests/s for 16.7 s, then the tuner is attached again.
    ev = quiet(0, 1.0) + [(1.0, DETACH)] + storm(1.0, 17.7) + [(17.7, ATTACH)] + quiet(17.7, 19)
    g, acts = run(ev)
    assert acts == [(1.0, "grab"), (17.7, "release", False, "tuner back")]
    assert g.state == dg.IDLE


def test_ordinary_retune_gives_the_keys_back():
    # Zap inside one satellite: detach and attach 0.63 s apart, no request storm.
    ev = quiet(0, 3.0) + [(1.0, DETACH), (1.63, ATTACH)]
    g, acts = run(ev)
    assert acts == [(1.0, "grab"), (1.35, "release", True, "no drive")]
    assert g.state == dg.IDLE
    # A very fast retune ends the hold at the attach line.
    _g, acts = run(quiet(0, 2.0) + [(1.0, DETACH), (1.2, ATTACH)])
    assert acts == [(1.0, "grab"), (1.2, "release", True, "retune")]


def test_detached_without_a_drive_never_holds_for_long():
    # e.g. an IPTV app: the tuner stays detached, the link stays at its normal rate.
    g, acts = run(quiet(0, 120.0) + [(1.0, DETACH)], until=120.0)
    assert acts == [(1.0, "grab"), (1.35, "release", True, "no drive")]
    assert g.state == dg.WATCH


def test_storm_that_starts_late_is_still_caught():
    ev = quiet(0, 2.0) + [(1.0, DETACH)] + storm(2.0, 12.0) + [(12.0, ATTACH)]
    _g, acts = run(ev)
    assert acts[:2] == [(1.0, "grab"), (1.35, "release", True, "no drive")]
    assert acts[2][1] == "grab" and 2.0 < acts[2][0] < 2.3
    assert acts[3] == (12.0, "release", False, "tuner back")


def test_hold_has_a_time_limit_and_ends_when_the_storm_stops():
    _g, acts = run([(1.0, DETACH)] + storm(1.0, 80.0), until=80.0)
    assert acts[0] == (1.0, "grab")
    assert acts[1][1:] == ("release", False, "time limit") and abs(acts[1][0] - (1.0 + dg.MAX_GRAB)) < 0.6
    assert len(acts) == 2                                   # no second hold without a new detach line
    # The attach line was lost (log overrun): the hold ends soon after the storm stops.
    _g, acts = run([(1.0, DETACH)] + storm(1.0, 11.0) + quiet(11.0, 20.0), until=20.0)
    assert acts[1][1:] == ("release", False, "drive ended") and 12.5 < acts[1][0] < 13.6


def test_second_satellite_change_after_the_hold_starts_a_new_hold():
    ev = ([(1.0, DETACH)] + storm(1.0, 16.7) + [(16.7, ATTACH), (17.5, DETACH)]
          + storm(17.5, 40.1) + [(40.1, ATTACH)])
    _g, acts = run(ev)
    assert [a[1] for a in acts] == ["grab", "release", "grab", "release"]
    assert acts[3] == (40.1, "release", False, "tuner back")


def test_other_kernel_lines_are_ignored():
    g, acts = run([(0.5, TSREAD), (0.6, b"4,1,1,-;conversion key [0x0af51ae5]\n")] + quiet(0, 2))
    assert acts == [] and g.state == dg.IDLE


def test_guard_is_stdlib_only_and_python39():
    source = SRC.read_text(encoding="utf-8")
    tree = ast.parse(source, feature_version=(3, 9))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or "").split(".")[0])
    assert mods <= {"collections", "errno", "fcntl", "os", "select", "struct", "sys", "time"}
    assert "\r" not in source                               # LF on the box


def test_find_remote_by_name():
    text = ('I: Bus=0003 Vendor=046d Product=c31c Version=0110\nN: Name="Logitech USB Keyboard"\n'
            'H: Handlers=sysrq kbd event0\n\n'
            'I: Bus=0000 Vendor=0000 Product=0000 Version=0000\nN: Name="dreambox advanced remote control"\n'
            'P: Phys=\nH: Handlers=kbd event1 gpufreq_interactive\n\n')
    assert dg.find_remote(text) == "/dev/input/event1"
    assert dg.find_remote('N: Name="Logitech USB Keyboard"\nH: Handlers=kbd event0\n') is None
    assert dg.find_remote("") is None
