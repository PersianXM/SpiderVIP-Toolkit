#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Root-cause pass for VidPid / FREEZE classification (lab only).

Phases: dual probe delta → OpenWebif → optional CH+/zap-back → classify.
No reboot.
"""
from __future__ import annotations

import re
import sys
import time

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import freeze_overlay as fo  # noqa: E402
import telnet_run as tr  # noqa: E402


def _wget(path: str) -> str:
    return (
        "(wget -qO- --timeout=4 'http://127.0.0.1:9095%s' 2>/dev/null "
        "|| wget -qO- --timeout=4 'http://127.0.0.1:80%s' 2>/dev/null "
        "|| echo WGET_EMPTY); echo WGET_DONE"
    ) % (path, path)


def _ref(text: str) -> str:
    m = re.search(r"<e2servicereference>([^<]+)</e2servicereference>", text or "", re.I)
    return m.group(1).strip() if m else ""


def _name(text: str) -> str:
    m = re.search(r"<e2servicename>([^<]*)</e2servicename>", text or "", re.I)
    return m.group(1).strip() if m else ""


def _line(snap: dict, key: str) -> str:
    it = snap.get(key) or {}
    return "%s=%s %s" % (key, it.get("tone"), (it.get("detail") or "")[:80])


def classify(snap: dict, webif_ok: bool) -> str:
    av = snap.get("av") or {}
    flow_ok = all(
        (snap.get(k) or {}).get("tone") == "OK" for k in ("stat", "vpss", "win", "adec", "vdec")
    )
    path_fail = any(
        (snap.get(k) or {}).get("tone") == "FAIL" for k in ("stat", "vpss", "vdec", "win", "adec")
    )
    detail = (av.get("detail") or "").lower()
    if path_fail:
        return "TRUE_AV_WEDGE"
    if not webif_ok:
        if av.get("tone") == "WARN" and "0x1fff" in detail and flow_ok:
            return "MSP_METADATA_STALE+CONTROL_PLANE_DEAD"
        return "CONTROL_PLANE_DEAD"
    if av.get("tone") == "WARN" and "0x1fff" in detail and flow_ok:
        return "MSP_METADATA_STALE"
    if av.get("tone") == "OK" and flow_ok:
        return "POLICY_FALSE_ALARM_RESOLVED"
    if fo.snap_is_freeze(snap):
        return "TRUE_AV_WEDGE"
    return "PARTIAL_HEALTH"


def main() -> int:
    print("=== PHASE1 probe A ===", flush=True)
    a = fo.probe()
    for k in fo.SENSOR_KEYS:
        print(" ", _line(a, k), flush=True)
    print("freeze=%s healthy=%s" % (fo.snap_is_freeze(a), fo.snap_is_healthy(a)), flush=True)

    print("Wait 12s for deltas...", flush=True)
    time.sleep(12)

    print("=== PHASE1 probe B ===", flush=True)
    b = fo.probe()
    for k in fo.SENSOR_KEYS:
        print(" ", _line(b, k), flush=True)
    print("freeze=%s healthy=%s" % (fo.snap_is_freeze(b), fo.snap_is_healthy(b)), flush=True)

    print("=== PHASE2 OpenWebif ===", flush=True)
    sock = tr.login()
    idx = 500
    about = tr.run(sock, _wget("/web/about"), idx, timeout=15)
    idx += 1
    cur = tr.run(sock, _wget("/web/getcurrent"), idx, timeout=15)
    idx += 1
    listeners = tr.run(
        sock,
        "netstat -lnt 2>/dev/null | grep -E ':80|:9095' || ss -lnt 2>/dev/null | grep -E ':80|:9095' || echo NO_LISTEN",
        idx,
        timeout=10,
    )
    idx += 1
    print("listeners:", (listeners or "").replace("\n", " | ")[:300], flush=True)
    print("about bytes:", len(about or ""), "getcurrent bytes:", len(cur or ""), flush=True)
    cur_ref = _ref(cur)
    cur_name = _name(cur)
    webif_ok = bool(cur_ref) or ("e2servicereference" in (cur or "").lower()) or (
        "enigma" in (about or "").lower()
    )
    print("CURRENT:", cur_name, "|", cur_ref, "webif_ok=", webif_ok, flush=True)

    if webif_ok and cur_ref:
        print("=== PHASE2 bounce CH+ / zap-back ===", flush=True)
        tr.run(sock, _wget("/web/remotecontrol?command=402"), idx, timeout=12)
        idx += 1
        time.sleep(4)
        zap = (
            "(wget -qO- --timeout=8 'http://127.0.0.1:9095/web/zap?sRef=%s' >/dev/null 2>&1 "
            "|| wget -qO- --timeout=8 'http://127.0.0.1:80/web/zap?sRef=%s' >/dev/null 2>&1) "
            "&& echo ZAP_OK || echo ZAP_FAIL"
        ) % (cur_ref, cur_ref)
        zout = tr.run(sock, zap, idx, timeout=20)
        idx += 1
        print("ZAP BACK:", "ZAP_OK" if "ZAP_OK" in (zout or "") else "ZAP_FAIL", flush=True)
        time.sleep(8)
    else:
        print("Skip bounce — OpenWebif not usable", flush=True)

    try:
        sock.sendall(b"exit\r\n")
        sock.close()
    except Exception:
        pass

    print("=== PHASE3 probe after control ===", flush=True)
    c = fo.probe()
    for k in fo.SENSOR_KEYS:
        print(" ", _line(c, k), flush=True)

    label = classify(c, webif_ok)
    print("=== PHASE4 CLASSIFY ===", label, flush=True)
    print(
        "av=%s freeze=%s | policy: VidPid-alone is WARN (0.9.3+)"
        % ((c.get("av") or {}).get("tone"), fo.snap_is_freeze(c)),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
