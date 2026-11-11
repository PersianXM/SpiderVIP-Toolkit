#!/usr/bin/env python3
"""On-box automatic frequency update (Python 3.9, standard library only).

Installed by the Console "Receiver patches" page to /data/spidervip_freq_auto/
with ``freqcore/`` (a copy of spidervip/frequency/core) and driven by ``loop.sh``.

  runner.py report   build the plan, write last_report.json, change nothing
  runner.py apply    phase 2: apply the whole plan (owner policy 2026-11-11:
                     every change, every new TP, every TP missing from the
                     source — except TPs that carry stored channels, which are
                     only listed as "candidates" in the report: 4 live TPs
                     with Al Jazeera, 2M Maroc and Arryadia were scanned under
                     Badr 26.0E but belong to Es'hail 1 25.5E in the source),
                     restore Motor, mark "pending verify", force-reboot
  runner.py verify   after that boot: compare TPs / unique channels / Motor;
                     on failure restore the snapshot once and force-reboot
  runner.py run      the mode in the ``mode`` file (default report)

Environment overrides exist only for tests (FA_*).
"""

import datetime
import filecmp
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from freqcore import lamedb as lamedb_mod  # noqa: E402
from freqcore import liveprog  # noqa: E402
from freqcore import plan as plan_mod  # noqa: E402
from freqcore import satxml, source  # noqa: E402

D = os.environ.get("FA_DIR", HERE)
ENIGMA = os.environ.get("FA_ENIGMA", "/data/gx/local/enigma_db")
SAT_XML = os.environ.get("FA_SAT_XML", ENIGMA + "/satellites.xml")
LAMEDB = os.environ.get("FA_LAMEDB", ENIGMA + "/lamedb")
LIVE_PROG = os.environ.get("FA_LIVE_PROG", "/data/gx/live_prog")
SNAP_ROOT = os.environ.get("FA_SNAP_ROOT", "/data/spidervip_freq")
RELOAD_URLS = os.environ.get("FA_RELOAD_URLS", "http://127.0.0.1/web/servicelistreload?mode=0 "
                                               "http://127.0.0.1:9095/web/servicelistreload?mode=0").split()
REBOOT_CMD = os.environ.get("FA_REBOOT_CMD", "sync; reboot -f")
REPORT = os.path.join(D, "last_report.json")
PENDING = os.path.join(D, "pending.json")
EXPECTED = os.path.join(D, "expected_satellites.xml")
LOCK = os.path.join(D, "run.lock")
KEEP_SNAPSHOTS = 3


# ---------------------------------------------------------------- helpers
def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(msg):
    print(f"{now_iso()} {msg}", flush=True)


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def write_atomic(path, data):
    tmp = path + ".spidervip.tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def sync():
    if hasattr(os, "sync"):
        os.sync()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_source():
    path = os.environ.get("FA_SOURCE_FILE")
    if not path:
        return source.load()
    data = read_bytes(path)
    sats = satxml.parse(data)
    return data, sats, source.describe(data, sats, url="file://" + path), source.validate(data, sats)


def bouquet_files():
    if not os.path.isdir(ENIGMA):
        return []
    return sorted(os.path.join(ENIGMA, n) for n in os.listdir(ENIGMA)
                  if n.startswith("userbouquet.") and n.endswith((".tv", ".radio")))


def unique_channels(lamedb_bytes):
    return lamedb_mod.service_stats(lamedb_bytes.decode("utf-8", "replace"))["unique"]


def reboot():
    try:
        os.rmdir(LOCK)  # the reboot ends this run; do not leave the lock behind
    except OSError:
        pass
    # The run that reboots counts as done for the schedule (loop.sh never sees rc).
    with open(os.path.join(D, "last_run"), "w") as fh:
        fh.write(f"{int(time.time())}\n")
    sync()
    subprocess.run(REBOOT_CMD, shell=True)  # noqa: S602 — fixed command from this file / tests


def reload_lists():
    errors = []
    for url in RELOAD_URLS:
        if url == "fake://":  # tests: imitate the box (commit + Motor reset)
            raw = bytearray(liveprog.unpack(read_bytes(LIVE_PROG)))
            for _n, off in liveprog.satellite_records(bytes(raw)):
                raw[off + liveprog.MOTOR_OFF] &= ~liveprog.MOTOR_MASK & 0xFF
            raw[-1] = (raw[-1] + 1) & 0xFF
            write_atomic(LIVE_PROG, liveprog.pack(bytes(raw)))
            return
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                body = resp.read().decode("utf-8", "replace")
            if "True" in body or "reloaded" in body.lower():
                return
            errors.append(f"{url}: {body[:80]!r}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
    raise RuntimeError("servicelistreload failed: " + "; ".join(errors))


def wait_stable(path, timeout=60.0, stable_for=6.0, step=1.0):
    deadline = time.time() + timeout
    last, since = None, None
    while time.time() < deadline:
        st = os.stat(path)
        sig = (st.st_mtime, st.st_size)
        if sig == last:
            if time.time() - since >= stable_for:
                return
        else:
            last, since = sig, time.time()
        time.sleep(step)


def snapshot():
    name = "snap_auto_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    d = os.path.join(SNAP_ROOT, name)
    os.makedirs(d)
    shutil.copy2(LIVE_PROG, os.path.join(d, "live_prog"))
    shutil.copytree(ENIGMA, os.path.join(d, "enigma_db"))
    sync()
    if not filecmp.cmp(LIVE_PROG, os.path.join(d, "live_prog"), shallow=False):
        raise RuntimeError("snapshot check failed (live_prog)")
    if not filecmp.cmp(SAT_XML, os.path.join(d, "enigma_db", "satellites.xml"), shallow=False):
        raise RuntimeError("snapshot check failed (satellites.xml)")
    return d


def prune(keep_also):
    if not os.path.isdir(SNAP_ROOT):
        return
    snaps = sorted((n for n in os.listdir(SNAP_ROOT) if n.startswith("snap_")), reverse=True)
    for n in snaps[KEEP_SNAPSHOTS:]:
        p = os.path.join(SNAP_ROOT, n)
        if p != keep_also:
            shutil.rmtree(p, ignore_errors=True)


def restore_snapshot(snap):
    """Whole-file restore (proven on the box: bit-exact, keeps Motor)."""

    shutil.copy2(os.path.join(snap, "live_prog"), LIVE_PROG)
    src = os.path.join(snap, "enigma_db")
    for name in os.listdir(src):
        shutil.copy2(os.path.join(src, name), os.path.join(ENIGMA, name))
    sync()


# ---------------------------------------------------------------- modes
def build_plan(delete_channel_tps):
    box = read_bytes(SAT_XML)
    lam = read_bytes(LAMEDB)
    src, src_sats, info, warnings = load_source()
    plan = plan_mod.build(box, src, lamedb_data=lam, source_info=info, warnings=warnings,
                          delete_channel_tps=delete_channel_tps)
    return box, lam, info, warnings, plan, src_sats


def summarize(plan, info, warnings, mode):
    t = plan["totals"]
    sats = []
    for s in plan["sats"]:
        c = s["counts"]
        if c["changed"] or c["new"] or c["gone"]:
            sats.append({"name": s["name"], "position": s["position_label"], "band": s["band"],
                         "counts": c, "deletions_preselected": s["guard"]["deletions_preselected"]})
    return {
        "ok": True, "mode": mode, "time": now_iso(),
        "source": {k: info.get(k) for k in ("created", "sats", "tps", "sha256")},
        "warnings": warnings,
        "box": {k: plan["box"].get(k) for k in ("sats", "tps", "channels", "channel_tps", "sha256")},
        "totals": t,
        "would_apply": {"changed": t["changed"], "new": t["new"], "removed": t["gone"],
                        "protected": t["protected"]},
        "sats": sats,
        "unmatched": len(plan["unmatched"]),
    }


def channel_removal(plan, sel, lam):
    """lamedb/bouquet edits for selected deletions of TPs that carry channels."""

    targets = plan_mod.deleted_channel_tps(plan, sel)
    new_text, removed_keys, removed_services = lamedb_mod.remove_transponders(
        lam.decode("utf-8", "replace"), targets)
    new_lam = new_text.encode("utf-8")
    bouquets, fav_removed = {}, 0
    for path in bouquet_files():
        text = read_bytes(path).decode("utf-8", "replace")
        new_b, n = lamedb_mod.filter_bouquet(text, removed_services)
        if n:
            bouquets[path] = new_b.encode("utf-8")
            fav_removed += n
    return {"targets": targets, "new_lam": new_lam, "removed_keys": removed_keys,
            "removed_services": removed_services, "bouquets": bouquets, "fav_removed": fav_removed,
            "channels_removed": unique_channels(lam) - unique_channels(new_lam)}


DELETE_CHANNEL_TPS = False  # owner decision 2026-11-11 ("method 1"): never delete TPs with channels


def candidates(plan, lam, src_sats=None):
    """Channel TPs missing from the source: kept, listed for the owner to decide.

    ``nearby`` names the same carrier on a neighbouring satellite in the source
    (a likely mis-stored scan, not an off-air TP).
    """

    POLS = {"0": "H", "1": "V", "2": "L", "3": "R"}
    targets, tps = [], []
    for s in plan["sats"]:
        for r in s["rows"]:
            if r["kind"] == "protected" and r.get("src") is None and r.get("box_attrs"):
                b = r["box_attrs"]
                t = (s["position"], int(b["frequency"]), b["polarization"], int(b["symbol_rate"]))
                targets.append(t)
                item = {"sat": s["name"], "freq": t[1] // 1000, "pol": POLS.get(t[2], t[2]), "sr": t[3] // 1000}
                near = satxml.nearby_tps(src_sats or [], s["position"], t[1], t[2])
                if near:
                    item["nearby"] = near
                tps.append(item)
    _new, _keys, services = lamedb_mod.remove_transponders(lam.decode("utf-8", "replace"), targets)
    return {"tps": tps, "channels": channel_names(lam, services, limit=60)}


def channel_names(lam, removed_services, limit=40):
    """Display names of removed services (from lamedb), for the report."""

    want = {":".join(s[:4]).lower() for s in removed_services}
    lines = lam.decode("utf-8", "replace").splitlines()
    out = []
    try:
        i = lines.index("services") + 1
    except ValueError:
        return out
    while i + 1 < len(lines) and lines[i] != "end":
        if ":".join(lines[i].split(":")[:4]).lower() in want and lines[i + 1] not in out:
            out.append(lines[i + 1])
        i += 3
    return out[:limit]


def report_only():
    t0 = time.time()
    _box, lam, info, warnings, plan, src_sats = build_plan(delete_channel_tps=DELETE_CHANNEL_TPS)
    rep = summarize(plan, info, warnings, "report")
    rep["candidates"] = candidates(plan, lam, src_sats)
    rep["seconds"] = round(time.time() - t0, 1)
    write_json(REPORT, rep)
    w = rep["would_apply"]
    log(f"report: {w['changed']} changed, {w['new']} new, {w['removed']} to remove; "
        f"source {info.get('created')}; {rep['seconds']}s")
    return 0


def apply():
    if os.path.exists(PENDING):
        log("apply skipped: a previous apply is still waiting for verification")
        return 3
    t0 = time.time()
    box, lam, info, warnings, plan, src_sats = build_plan(delete_channel_tps=DELETE_CHANNEL_TPS)
    rep = summarize(plan, info, warnings, "apply")
    rep["candidates"] = candidates(plan, lam, src_sats)
    sel = plan_mod.full_selection(plan)
    if not sel:
        rep.update(result="nothing", seconds=round(time.time() - t0, 1))
        write_json(REPORT, rep)
        log("apply: nothing to change")
        return 0
    res = plan_mod.apply(box, plan, sel)
    cr = channel_removal(plan, sel, lam)
    targets, new_lam, removed_keys = cr["targets"], cr["new_lam"], cr["removed_keys"]
    bouquets, fav_removed = cr["bouquets"], cr["fav_removed"]
    rep["channel_removal"] = {"tps": len(targets), "channels": cr["channels_removed"],
                              "favorite_entries": fav_removed,
                              "names": channel_names(lam, cr["removed_services"])}
    motor = liveprog.motor_map(liveprog.unpack(read_bytes(LIVE_PROG)))
    ch_before = unique_channels(lam)
    ch_expected = unique_channels(new_lam)

    snap = snapshot()
    log(f"apply: snapshot {snap}; {res['summary']}; channel TPs removed {len(targets)}, "
        f"channels removed {ch_before - ch_expected}, favorite entries removed {fav_removed}")
    try:
        write_atomic(SAT_XML, res["xml"])
        if removed_keys:
            write_atomic(LAMEDB, new_lam)
        for path, data in bouquets.items():
            write_atomic(path, data)
        sync()
        before = read_bytes(LIVE_PROG)
        reload_lists()
        for _ in range(15):
            if read_bytes(LIVE_PROG) != before:
                break
            time.sleep(1)
        wait_stable(LIVE_PROG)
        raw = liveprog.unpack(read_bytes(LIVE_PROG))
        patched, restored, missing = liveprog.restore_motor(raw, motor)
        if restored:
            write_atomic(LIVE_PROG, liveprog.pack(patched))
    except Exception as exc:  # noqa: BLE001 — nothing committed for sure: put the snapshot back
        restore_snapshot(snap)
        rep.update(ok=False, result="error_restored", error=f"{type(exc).__name__}: {exc}", snapshot=snap,
                   seconds=round(time.time() - t0, 1))
        write_json(REPORT, rep)
        log(f"apply FAILED, snapshot restored, rebooting: {exc}")
        reboot()
        return 2
    write_atomic(EXPECTED, res["xml"])
    write_json(PENDING, {
        "stage": "applied", "time": now_iso(), "snapshot": snap,
        "expected_sha": res["sha256"], "channels_before": ch_before, "channels_expected": ch_expected,
        "motor": {k: list(v) for k, v in motor.items()}, "motor_restored": restored, "motor_missing": missing,
        "summary": res["summary"], "channel_tps_removed": len(targets),
        "channels_removed": ch_before - ch_expected, "favorite_entries_removed": fav_removed,
        "report": rep,
    })
    prune(keep_also=snap)
    log("apply: done, force-rebooting for verification")
    reboot()
    return 0


def verify():
    if not os.path.exists(PENDING):
        return 0
    with open(PENDING, encoding="utf-8") as fh:
        pending = json.load(fh)
    rep = pending.get("report", {})
    motor = {k: tuple(v) for k, v in pending.get("motor", {}).items()}
    actual = read_bytes(SAT_XML)
    problems = []
    if pending["stage"] == "applied":
        cmp_ok = satxml.signatures_by_sat(satxml.parse(actual)) == satxml.signatures_by_sat(
            satxml.parse(read_bytes(EXPECTED)))
        if not cmp_ok:
            problems.append("TP list differs from the plan")
    else:  # rolled back: compare with the snapshot's list
        snap_xml = read_bytes(os.path.join(pending["snapshot"], "enigma_db", "satellites.xml"))
        if satxml.signatures_by_sat(satxml.parse(actual)) != satxml.signatures_by_sat(satxml.parse(snap_xml)):
            problems.append("TP list differs from the snapshot after rollback")
    ch_now = unique_channels(read_bytes(LAMEDB))
    need = pending["channels_expected"] if pending["stage"] == "applied" else pending["channels_before"]
    if ch_now < need:
        problems.append(f"unique channels {ch_now} < {need}")
    try:
        diff = liveprog.motor_differences(liveprog.unpack(read_bytes(LIVE_PROG)), motor)
    except Exception as exc:  # noqa: BLE001
        diff = [f"live_prog unreadable: {exc}"]
    if diff:
        problems.append("Motor not restored: " + ", ".join(diff))

    if pending["stage"] == "applied" and problems:
        log("verify FAILED, rolling back: " + "; ".join(problems))
        restore_snapshot(pending["snapshot"])
        pending.update(stage="rolled_back", problems=problems, rollback_time=now_iso())
        write_json(PENDING, pending)
        reboot()
        return 2
    os.remove(PENDING)
    if pending["stage"] == "applied":
        rep.update(result="applied", verified_time=now_iso(), channels_after=ch_now,
                   **{k: pending[k] for k in ("summary", "snapshot", "channel_tps_removed", "channels_removed",
                                              "favorite_entries_removed", "motor_restored")})
        log(f"verify ok: {pending['summary']}; unique channels {pending['channels_before']} -> {ch_now}")
    else:
        rep.update(ok=False, result="rolled_back", problems=pending.get("problems"),
                   rollback_ok=not problems, rollback_problems=problems, snapshot=pending["snapshot"])
        log("rollback verified" if not problems else "rollback check problems: " + "; ".join(problems))
    write_json(REPORT, rep)
    return 0


def main(argv):
    mode = argv[1] if len(argv) > 1 else "run"
    if mode == "run":
        try:
            mode = open(os.path.join(D, "mode"), encoding="utf-8").read().strip() or "report"
        except OSError:
            mode = "report"
    if mode == "verify":
        return verify()
    try:
        os.mkdir(LOCK)  # one run at a time (loop and "run now" can overlap)
    except FileExistsError:
        if time.time() - os.path.getmtime(LOCK) < 3600:
            log("another run is active, skipped")
            return 3
        os.rmdir(LOCK)
        os.mkdir(LOCK)
    try:
        return apply() if mode == "apply" else report_only()
    except Exception as exc:  # noqa: BLE001 — keep the last good report, record the failure
        write_json(os.path.join(D, "last_error.json"),
                   {"ok": False, "mode": mode, "time": now_iso(), "error": f"{type(exc).__name__}: {exc}"})
        log(f"{mode} FAILED: {type(exc).__name__}: {exc}")
        return 2
    finally:
        try:
            os.rmdir(LOCK)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main(sys.argv))
