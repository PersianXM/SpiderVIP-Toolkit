#!/usr/bin/env python3
"""On-box frequency update runner (Python 3.9, standard library only).

Installed by the Console "Receiver patches" page to /data/spidervip_freq_auto/
together with ``freqcore/`` (a copy of spidervip/frequency/core) and started by
``loop.sh``. Phase 1 = report only: it downloads the daily OpenPLi list, builds
the same plan as the PC tool against the receiver's own lists, and writes
``last_report.json``. It never changes anything on the receiver.

Environment overrides exist only for tests:
  FA_DIR, FA_SAT_XML, FA_LAMEDB, FA_SOURCE_FILE (use a local file, no download)
"""

import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from freqcore import plan as plan_mod  # noqa: E402
from freqcore import satxml, source  # noqa: E402

D = os.environ.get("FA_DIR", HERE)
SAT_XML = os.environ.get("FA_SAT_XML", "/data/gx/local/enigma_db/satellites.xml")
LAMEDB = os.environ.get("FA_LAMEDB", "/data/gx/local/enigma_db/lamedb")
REPORT = os.path.join(D, "last_report.json")
LOCK = os.path.join(D, "run.lock")


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def load_source():
    path = os.environ.get("FA_SOURCE_FILE")
    if not path:
        return source.load()
    data = read_bytes(path)
    sats = satxml.parse(data)
    warnings = source.validate(data, sats)
    return data, sats, source.describe(data, sats, url="file://" + path), warnings


def report_only():
    t0 = time.time()
    box = read_bytes(SAT_XML)
    lam = read_bytes(LAMEDB)
    src, _sats, info, warnings = load_source()
    plan = plan_mod.build(box, src, lamedb_data=lam, source_info=info, warnings=warnings)
    t = plan["totals"]
    sats = []
    for s in plan["sats"]:
        c = s["counts"]
        if c["changed"] or c["new"] or c["gone"]:
            sats.append({"name": s["name"], "position": s["position_label"], "band": s["band"],
                         "counts": c, "deletions_preselected": s["guard"]["deletions_preselected"]})
    return {
        "ok": True,
        "mode": "report",
        "time": now_iso(),
        "seconds": round(time.time() - t0, 1),
        "source": {k: info.get(k) for k in ("created", "sats", "tps", "sha256")},
        "warnings": warnings,
        "box": {k: plan["box"].get(k) for k in ("sats", "tps", "channels", "channel_tps", "sha256")},
        "totals": t,
        "would_apply": {"changed": t["changed"], "new": t["new"], "removed": t["gone_preselected"],
                        "protected": t["protected"]},
        "sats": sats,
        "unmatched": len(plan["unmatched"]),
    }


def main():
    try:
        os.mkdir(LOCK)  # atomic: one run at a time (loop and "run now" can overlap)
    except FileExistsError:
        age = time.time() - os.path.getmtime(LOCK)
        if age < 3600:
            print(f"{now_iso()} another run is active, skipped")
            return 3
        os.rmdir(LOCK)
        os.mkdir(LOCK)
    try:
        result = report_only()
        w = result["would_apply"]
        print(f"{now_iso()} report: {w['changed']} changed, {w['new']} new, {w['removed']} to remove, "
              f"{w['protected']} protected; source {result['source']['created']}; {result['seconds']}s")
        code = 0
    except Exception as exc:  # noqa: BLE001 — keep the last good report, record the failure
        result = {"ok": False, "mode": "report", "time": now_iso(), "error": f"{type(exc).__name__}: {exc}"}
        print(f"{now_iso()} report FAILED: {result['error']}")
        code = 2
    finally:
        try:
            os.rmdir(LOCK)
        except OSError:
            pass
    if result.get("ok"):
        write_json(REPORT, result)
    else:
        write_json(os.path.join(D, "last_error.json"), result)
    return code


if __name__ == "__main__":
    sys.exit(main())
