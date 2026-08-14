#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot: CH+ then zap back to previous service; report VidPid / AV tone.

Lab-only helper — not part of the product UI.
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
        "(wget -qO- --timeout=5 'http://127.0.0.1:9095%s' 2>/dev/null "
        "|| wget -qO- --timeout=5 'http://127.0.0.1:80%s' 2>/dev/null "
        "|| wget -qO- --timeout=5 'http://127.0.0.1%s' 2>/dev/null "
        "|| echo WGET_EMPTY); echo WGET_DONE"
    ) % (path, path, path)


def _zap(ref: str) -> str:
    return (
        "(wget -qO- --timeout=8 'http://127.0.0.1:9095/web/zap?sRef=%s' >/dev/null 2>&1 "
        "|| wget -qO- --timeout=8 'http://127.0.0.1:80/web/zap?sRef=%s' >/dev/null 2>&1 "
        "|| wget -qO- --timeout=8 'http://127.0.0.1/web/zap?sRef=%s' >/dev/null 2>&1) "
        "&& echo ZAP_OK || echo ZAP_FAIL"
    ) % (ref, ref, ref)


def _ref(text: str) -> str:
    m = re.search(r"<e2servicereference>([^<]+)</e2servicereference>", text or "", re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r'"service_reference"\s*:\s*"([^"]+)"', text or "")
    return m.group(1).strip() if m else ""


def _name(text: str) -> str:
    m = re.search(r"<e2servicename>([^<]*)</e2servicename>", text or "", re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r'"service_name"\s*:\s*"([^"]*)"', text or "")
    return m.group(1).strip() if m else ""


def _av_line(snap: dict) -> str:
    av = snap.get("av") or {}
    return "tone=%s play=%s detail=%s" % (av.get("tone"), av.get("play"), av.get("detail"))


def main() -> int:
    print("=== BEFORE ===", flush=True)
    before = fo.probe()
    print(_av_line(before), flush=True)
    print("win:", (before.get("win") or {}).get("detail"), flush=True)
    print("adec:", (before.get("adec") or {}).get("detail"), flush=True)

    sock = tr.login()
    idx = 300
    cur_xml = tr.run(sock, _wget("/web/getcurrent"), idx, timeout=20)
    idx += 1
    print("getcurrent bytes:", len(cur_xml or ""), flush=True)
    print((cur_xml or "")[:600], flush=True)
    cur_ref = _ref(cur_xml)
    cur_name = _name(cur_xml)
    print("CURRENT:", cur_name, "|", cur_ref, flush=True)

    if not cur_ref:
        # Fallback: known lab channel (Iran International HD)
        cur_ref = fo.ZAP_REF
        cur_name = cur_name or "(fallback ZAP_REF)"
        print("WARN: using fallback ref", cur_ref, flush=True)

    up = tr.run(sock, _wget("/web/remotecontrol?command=402"), idx, timeout=15)
    idx += 1
    print("CH+ done; result has result:", "result" in (up or "").lower(), flush=True)
    print("Wait 4s on neighbor...", flush=True)
    time.sleep(4)

    nb = tr.run(sock, _wget("/web/getcurrent"), idx, timeout=20)
    idx += 1
    print("NEIGHBOR:", _name(nb), "|", _ref(nb), flush=True)

    zap_out = tr.run(sock, _zap(cur_ref), idx, timeout=25)
    idx += 1
    zap_ok = "ZAP_OK" in (zap_out or "")
    print("ZAP BACK:", "ZAP_OK" if zap_ok else "ZAP_FAIL", flush=True)
    print("Wait 8s for A/V lock...", flush=True)
    time.sleep(8)

    back = tr.run(sock, _wget("/web/getcurrent"), idx, timeout=20)
    idx += 1
    print("BACK:", _name(back), "|", _ref(back), flush=True)

    raw = tr.run(
        sock,
        "grep -E 'CurStatus|Vid Enable|VidPid|Aud Enable' /proc/msp/avplay00 2>/dev/null | head -8; echo RAW_DONE",
        idx,
        timeout=12,
    )
    print("RAW AV:", flush=True)
    for ln in (raw or "").splitlines():
        s = ln.strip()
        if any(k in s for k in ("CurStatus", "Vid", "Aud", "VidPid", "RAW")):
            print(" ", s, flush=True)

    try:
        sock.sendall(b"exit\r\n")
        sock.close()
    except Exception:
        pass

    print("=== AFTER ===", flush=True)
    after = fo.probe()
    print(_av_line(after), flush=True)
    print("win:", (after.get("win") or {}).get("detail"), flush=True)
    print("adec:", (after.get("adec") or {}).get("detail"), flush=True)
    print(
        "freeze=%s healthy=%s"
        % (fo.snap_is_freeze(after), fo.snap_is_healthy(after)),
        flush=True,
    )
    tone = (after.get("av") or {}).get("tone")
    print("RESULT:", "FIXED" if tone == "OK" else "NOT_FIXED", flush=True)
    return 0 if tone == "OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
