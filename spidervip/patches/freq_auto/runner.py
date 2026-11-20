#!/usr/bin/env python3
"""On-box automatic frequency update (Python 3.9, standard library only).

Installed by the Console "Receiver patches" page to /data/spidervip_freq_auto/
with ``freqcore/`` (a copy of spidervip/frequency/core) and driven by ``loop.sh``.

  runner.py report   build the plan, write last_report.json, change nothing
  runner.py apply    phase 2: apply the whole plan (owner policy 2026-11-11/12:
                     every change, every new TP, every new satellite (USALS),
                     every receiver satellite missing from the source that no
                     channel uses, every TP missing from the source — except TPs that carry stored channels, which are
                     only listed as "candidates" in the report: 4 live TPs
                     with Al Jazeera, 2M Maroc and Arryadia were scanned under
                     Badr 26.0E but belong to Es'hail 1 25.5E in the source),
                     restore Motor, mark "pending verify", force-reboot
  runner.py verify   after that boot: compare TPs / unique channels / Motor /
                     service types / favorite lists; on failure restore the
                     snapshot once and force-reboot
  runner.py repair-hd SNAP  one-time: put back HEVC HD services (type 31) and
                     their favorite entries that an older run lost (2026-11-20)
  runner.py run      the mode in the ``mode`` file (default report)

HEVC HD (2026-11-20): the box's lamedb import, run by every servicelistreload,
does not know service type 31; it turns those services into radio entries with
channel number 0, so they vanish from the TV favorites. Before the reload the
type is written as 25 (lamedb.STANDIN_TYPES) and afterwards put back in
live_prog (liveprog.restore_service_types); unknown types block the apply.

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
        if url == "fake://":  # tests: imitate the box (table rebuilt from the XML, Motor reset)
            old = liveprog.unpack(read_bytes(LIVE_PROG))
            recs = liveprog.satellite_records(old)
            by_name = {n: old[o:o + liveprog.REC] for n, o in recs}
            table = bytearray()
            for sat in satxml.parse(read_bytes(SAT_XML)):
                key = liveprog.record_name(sat.name)
                rec = bytearray(by_name.get(key) or bytes(liveprog.REC))
                if key not in by_name:
                    rec[:liveprog.NAME_LEN - 1] = key.encode("latin-1").ljust(liveprog.NAME_LEN - 1, bytes(1))
                    rec[liveprog.MOTOR_OFF], rec[liveprog.POSITIONER_OFF] = 0x51, 0xFF
                rec[liveprog.MOTOR_OFF] &= ~liveprog.MOTOR_MASK & 0xFF
                table += rec
            raw = bytearray(table + old[len(recs) * liveprog.REC:])
            raw[-1] = (raw[-1] + 1) & 0xFF
            _fake_import_services(raw)
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


def _fake_import_services(raw):
    """Tests: imitate the box's lamedb import into the service table (types it
    does not know become radio entries with channel number 0)."""

    lines = read_bytes(LAMEDB).decode("utf-8", "replace").splitlines()
    by_sid = {}
    for i in lamedb_mod._services(lines):  # noqa: SLF001 — test helper
        p = lines[i].split(":")
        if len(p) >= 6 and i + 1 < len(lines):
            by_sid[(int(p[0], 16), lines[i + 1].encode("utf-8"))] = (int(p[4]), int(p[5]))
    for s in liveprog.services(bytes(raw)):
        got = by_sid.get((s["sid"], s["name"]))
        if got is None:
            continue
        t, num = got
        off = s["off"]
        known = t in lamedb_mod.IMPORTER_TYPES
        raw[off + liveprog.SVC_TYPE] = t & 0xFF
        if not known or t == 2:
            raw[off + liveprog.SVC_FLAGS] |= liveprog.SVC_RADIO
        else:
            raw[off + liveprog.SVC_FLAGS] &= ~liveprog.SVC_RADIO & 0xFF
        num = num if known else 0
        raw[off + liveprog.SVC_NUM:off + liveprog.SVC_NUM + 2] = num.to_bytes(2, "little")
    # The box exports lamedb and the favorites at the reload (not at boot).
    svcs = {s["sid"]: s for s in liveprog.services(bytes(raw))}
    if not svcs:
        return
    out = []
    for ln in read_bytes(LAMEDB).decode("utf-8").splitlines(keepends=True):
        p = ln.rstrip("\n").split(":")
        if len(p) >= 6 and len(p[0]) == 4 and int(p[0], 16) in svcs:
            s = svcs[int(p[0], 16)]
            p[4], p[5] = ("0", "0") if s["radio"] and s["type"] != 2 else (str(s["type"]), str(s["number"]))
            ln = ":".join(p) + "\n"
        out.append(ln)
    write_atomic(LAMEDB, "".join(out).encode("utf-8"))
    for path in bouquet_files():
        out = []
        for ln in read_bytes(path).decode("utf-8").splitlines(keepends=True):
            if ln.startswith("#SERVICE "):
                r = ln.strip()[len("#SERVICE "):].split(":")
                s = svcs.get(int(r[3], 16)) if len(r) > 6 else None
                if s is not None:
                    if s["radio"] and path.endswith(".tv"):
                        continue
                    r[2] = f"{s['type']:X}"
                    ln = "#SERVICE " + ":".join(r) + "\n"
            out.append(ln)
        write_atomic(path, "".join(out).encode("utf-8"))


def rewrite_exports(keys):
    """Write the real type back into the box's own export (lamedb, userbouquets)
    for the stand-in services. The box does not re-export at boot (live
    2026-11-20: files kept their pre-reboot time), so without this the files
    keep showing type 25 / ``19`` although live_prog has 31 again."""

    if not keys:
        return
    inv = {v: k for k, v in lamedb_mod.STANDIN_TYPES.items()}
    wait_stable(LAMEDB, timeout=30.0, stable_for=4.0)
    text = read_bytes(LAMEDB).decode("utf-8", "replace")
    new, changed = lamedb_mod.substitute_types(text, standin=inv, only=keys)
    if changed:
        write_atomic(LAMEDB, new.encode("utf-8"))
    for path in bouquet_files():
        text = read_bytes(path).decode("utf-8", "replace")
        new, n = lamedb_mod.substitute_bouquet_types(text, keys, standin=inv)
        if n:
            write_atomic(path, new.encode("utf-8"))
    sync()


def hd_services(raw):
    """``[[sid, name hex, type]]`` of TV services whose type needs the stand-in (for verify)."""

    return [[s["sid"], s["name"].hex(), s["type"]] for s in liveprog.services(raw)
            if s["type"] in lamedb_mod.STANDIN_TYPES and not s["radio"]]


def reload_and_restore(motor_target, force=(), keys=()):
    """servicelistreload, wait until live_prog settles, then put back what the
    import loses: service types it does not know (see lamedb.STANDIN_TYPES)
    and Motor settings. Raises if the services did not come back as expected."""

    before = read_bytes(LIVE_PROG)
    before_raw = liveprog.unpack(before)
    reload_lists()
    for _ in range(15):
        if read_bytes(LIVE_PROG) != before:
            break
        time.sleep(1)
    wait_stable(LIVE_PROG)
    raw0 = liveprog.unpack(read_bytes(LIVE_PROG))
    raw, types_restored, problems = liveprog.restore_service_types(
        before_raw, raw0, lamedb_mod.STANDIN_TYPES, force=force)
    if problems:
        raise RuntimeError("services after reload: " + "; ".join(problems[:8]))
    patched, restored, missing = liveprog.restore_motor(raw, motor_target)
    if patched != raw0:
        write_atomic(LIVE_PROG, liveprog.pack(patched))
    rewrite_exports(keys)
    return restored, missing, types_restored, hd_services(patched)


def hd_guard(lam, new_lam, bouquets):
    """Prepare lamedb/bouquets for the reload and what verify must find afterwards.

    Services of a type the importer cannot keep get the stand-in type (also in
    their favorite references); verify then requires every service type and
    every favorite list to come back exactly as intended.
    """

    text = new_lam.decode("utf-8", "replace")
    # FA_TEST_NO_STANDIN: tests only — reload without the stand-in, like before 2026-11-20.
    sub_text, keys = lamedb_mod.substitute_types(text, {} if os.environ.get("FA_TEST_NO_STANDIN") else None)
    out, exp_refs, before_refs = {}, {}, {}
    for path in bouquet_files():
        orig = read_bytes(path)
        intended = bouquets.get(path, orig).decode("utf-8", "replace")
        name = os.path.basename(path)
        before_refs[name] = lamedb_mod.bouquet_refs(orig.decode("utf-8", "replace"))
        exp_refs[name] = lamedb_mod.bouquet_refs(intended)
        sub, n = lamedb_mod.substitute_bouquet_types(intended, keys)
        if path in bouquets or n:
            out[path] = sub.encode("utf-8")
    return {"lamedb": sub_text.encode("utf-8"), "keys": keys, "bouquets": out,
            "expect": {"types_expected": lamedb_mod.service_types(text),
                       "types_before": lamedb_mod.service_types(lam.decode("utf-8", "replace")),
                       "bouquets_expected": exp_refs, "bouquets_before": before_refs}}


def list_problems(types_want, bouquets_want):
    """Service types and favorite lists that differ from what was intended."""

    problems = []
    if types_want:
        now = lamedb_mod.service_types(read_bytes(LAMEDB).decode("utf-8", "replace"))
        bad = sorted(k for k, t in types_want.items() if k in now and now[k] != t)
        if bad:
            problems.append(f"service type changed on {len(bad)} channels ({', '.join(bad[:5])})")
    for name, refs in (bouquets_want or {}).items():
        path = os.path.join(ENIGMA, name)
        now = lamedb_mod.bouquet_refs(read_bytes(path).decode("utf-8", "replace")) if os.path.exists(path) else []
        if now != refs:
            problems.append(f"favorites changed: {name} ({len(refs)} -> {len(now)} entries)")
    return problems


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
                        "protected": t["protected"],
                        "sats_new": t.get("sats_new", 0), "sats_new_tps": t.get("sats_new_tps", 0),
                        "sats_removed": t.get("sats_removable", 0),
                        "sats_removed_tps": t.get("sats_removable_tps", 0)},
        "new_sats": [{"name": s["name"], "position": s["position_label"], "tps": s["count"]}
                     for s in plan.get("new_sats", [])],
        "removed_sats": [{"name": u["name"], "position": u["position_label"], "tps": u["box_count"]}
                         for u in plan.get("unmatched", []) if u.get("removable")],
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
    unknown = lamedb_mod.unknown_types(lam.decode("utf-8", "replace"))
    if unknown:
        # The reload would turn these services into radio entries and drop them from favorites.
        rep.update(ok=False, result="blocked_service_types", unknown_types=unknown,
                   seconds=round(time.time() - t0, 1))
        write_json(REPORT, rep)
        log(f"apply blocked: service types the receiver's import cannot keep: {unknown}")
        return 0
    res = plan_mod.apply(box, plan, sel)
    cr = channel_removal(plan, sel, lam)
    targets, new_lam, removed_keys = cr["targets"], cr["new_lam"], cr["removed_keys"]
    bouquets, fav_removed = cr["bouquets"], cr["fav_removed"]
    guard = hd_guard(lam, new_lam, bouquets)
    rep["channel_removal"] = {"tps": len(targets), "channels": cr["channels_removed"],
                              "favorite_entries": fav_removed,
                              "names": channel_names(lam, cr["removed_services"])}
    motor = liveprog.motor_map(liveprog.unpack(read_bytes(LIVE_PROG)))
    # New satellites get USALS, removed ones leave the map (owner decision 2026-11-12).
    motor_target = liveprog.target_motor(motor, added=res["summary"]["sats_added"],
                                         removed=res["summary"]["sats_removed"])
    ch_before = unique_channels(lam)
    ch_expected = unique_channels(new_lam)

    snap = snapshot()
    log(f"apply: snapshot {snap}; {res['summary']}; channel TPs removed {len(targets)}, "
        f"channels removed {ch_before - ch_expected}, favorite entries removed {fav_removed}")
    try:
        write_atomic(SAT_XML, res["xml"])
        if removed_keys or guard["keys"]:
            write_atomic(LAMEDB, guard["lamedb"])
        for path, data in guard["bouquets"].items():
            write_atomic(path, data)
        sync()
        restored, missing, types_restored, hd = reload_and_restore(motor_target, keys=guard["keys"])
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
        "motor": {k: list(v) for k, v in motor.items()},
        "motor_target": {k: list(v) for k, v in motor_target.items()},
        "motor_restored": restored, "motor_missing": missing,
        "summary": res["summary"], "channel_tps_removed": len(targets),
        "channels_removed": ch_before - ch_expected, "favorite_entries_removed": fav_removed,
        "types_restored": types_restored, "hd_services": hd,
        **guard["expect"],
        "report": rep,
    })
    prune(keep_also=snap)
    log("apply: done, force-rebooting for verification")
    reboot()
    return 0


def _service_entries(text):
    """``{key: (type, number, name)}`` from lamedb text (first entry wins)."""

    lines = text.splitlines()
    out = {}
    for i in lamedb_mod._services(lines):  # noqa: SLF001
        p = lines[i].split(":")
        if len(p) >= 6 and i + 1 < len(lines):
            key = ":".join(p[:4]).lower()
            if key not in out:
                try:
                    out[key] = (int(p[4]), int(p[5]), lines[i + 1])
                except ValueError:
                    pass
    return out


def repair_hd(snap):
    """One-time repair after an older run (before 2026-11-20) mangled HEVC HD
    services: put their type/number and their favorite entries back from
    ``snap`` (a snapshot taken before that run), through the same reload +
    live_prog restore + verify path as an apply. The TP list is not touched."""

    if os.path.exists(PENDING):
        log("repair skipped: a previous apply is still waiting for verification")
        return 3
    snap_lam = read_bytes(os.path.join(snap, "enigma_db", "lamedb")).decode("utf-8", "replace")
    lam = read_bytes(LAMEDB)
    cur = _service_entries(lam.decode("utf-8", "replace"))
    old = _service_entries(snap_lam)
    fix = {k: (t, n) for k, (t, n, _name) in old.items()
           if t in lamedb_mod.STANDIN_TYPES and k in cur and cur[k][0] != t}
    if not fix:
        log("repair: nothing to repair")
        return 0
    names = [old[k][2] for k in fix]
    force = {(int(k.split(":")[0], 16), old[k][2].encode("utf-8")) for k in fix}
    new_lam_text, _keys = lamedb_mod.substitute_types(lam.decode("utf-8", "replace"), numbers=fix)
    real_lam_text, _ = lamedb_mod.substitute_types(lam.decode("utf-8", "replace"), standin={},
                                                   numbers=fix)
    # Favorite lists: take the snapshot's version only where the difference is
    # exactly the entries of the repaired services.
    fixed_refs = set()
    for k in fix:
        sid, ns, tsid, onid = (int(x, 16) for x in k.split(":"))
        fixed_refs.add((sid, ns, tsid, onid))

    def ref_key(line):
        r = line[len("#SERVICE "):].split(":")
        try:
            return (int(r[3], 16), int(r[6], 16), int(r[4], 16), int(r[5], 16))
        except (IndexError, ValueError):
            return None

    bouquets, intended, skipped = {}, {}, []
    for path in bouquet_files():
        name = os.path.basename(path)
        snap_path = os.path.join(snap, "enigma_db", name)
        now_text = read_bytes(path).decode("utf-8", "replace")
        if not os.path.exists(snap_path):
            continue
        snap_text = read_bytes(snap_path).decode("utf-8", "replace")
        now_refs, snap_refs = lamedb_mod.bouquet_refs(now_text), lamedb_mod.bouquet_refs(snap_text)
        if now_refs == snap_refs:
            continue
        if [r for r in snap_refs if ref_key(r) not in fixed_refs] != now_refs:
            skipped.append(name)
            continue
        bouquets[path] = lamedb_mod.substitute_bouquet_types(snap_text, fix.keys())[0].encode("utf-8")
        intended[name] = snap_refs
        if os.path.exists(snap_path + ".simple"):  # index form; record indexes do not move
            bouquets[path + ".simple"] = read_bytes(snap_path + ".simple")
    # What verify must find, taken before anything is written.
    sat_before = read_bytes(SAT_XML)
    want_bouquets = {os.path.basename(p): lamedb_mod.bouquet_refs(read_bytes(p).decode("utf-8", "replace"))
                     for p in bouquet_files()}
    want_bouquets.update(intended)  # the box must show the real type, not the stand-in we write
    motor = liveprog.motor_map(liveprog.unpack(read_bytes(LIVE_PROG)))
    ch_before = unique_channels(lam)
    snap_now = snapshot()
    log(f"repair: snapshot {snap_now}; {len(fix)} services ({', '.join(names)}); favorites from {snap}: "
        f"{sorted(intended)}; skipped {skipped}")
    rep = {"ok": True, "mode": "repair-hd", "time": now_iso(), "repaired": names,
           "favorites": sorted(intended), "skipped": skipped}
    try:
        write_atomic(LAMEDB, new_lam_text.encode("utf-8"))
        for path, data in bouquets.items():
            write_atomic(path, data)
        sync()
        restored, missing, types_restored, hd = reload_and_restore(motor, force=force, keys=list(fix))
        lost = [s["name"].decode("utf-8", "replace") for s in liveprog.services(liveprog.unpack(read_bytes(LIVE_PROG)))
                if (s["sid"], s["name"]) in force and (s["radio"] or not s["number"])]
        if lost or len(types_restored) < len(fix):
            raise RuntimeError(f"repaired services not back as TV: {lost or types_restored}")
    except Exception as exc:  # noqa: BLE001
        restore_snapshot(snap_now)
        rep.update(ok=False, result="error_restored", error=f"{type(exc).__name__}: {exc}", snapshot=snap_now)
        write_json(REPORT, rep)
        log(f"repair FAILED, snapshot restored, rebooting: {exc}")
        reboot()
        return 2
    write_atomic(EXPECTED, sat_before)
    types_before = lamedb_mod.service_types(lam.decode("utf-8", "replace"))
    write_json(PENDING, {
        "stage": "applied", "time": now_iso(), "snapshot": snap_now,
        "channels_before": ch_before, "channels_expected": ch_before,
        "motor": {k: list(v) for k, v in motor.items()},
        "motor_target": {k: list(v) for k, v in motor.items()},
        "motor_restored": restored, "motor_missing": missing,
        "summary": {"repair_hd": names}, "channel_tps_removed": 0, "channels_removed": 0,
        "favorite_entries_removed": 0, "types_restored": types_restored, "hd_services": hd,
        "types_expected": lamedb_mod.service_types(real_lam_text), "types_before": types_before,
        "bouquets_expected": want_bouquets,
        "bouquets_before": {os.path.basename(p): lamedb_mod.bouquet_refs(read_bytes(os.path.join(snap_now, "enigma_db", os.path.basename(p))).decode("utf-8", "replace")) for p in bouquet_files()},
        "report": rep,
    })
    # No prune here: the snapshot the repair came from must survive.
    log("repair: done, force-rebooting for verification")
    reboot()
    return 0


def verify():
    if not os.path.exists(PENDING):
        return 0
    with open(PENDING, encoding="utf-8") as fh:
        pending = json.load(fh)
    rep = pending.get("report", {})
    # After an apply the box must have the target Motor map; after a rollback, the original.
    key = "motor_target" if pending["stage"] == "applied" and "motor_target" in pending else "motor"
    motor = {k: tuple(v) for k, v in pending.get(key, {}).items()}
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
    # Service types and favorites (added 2026-11-20; older pending files have neither).
    if pending["stage"] == "applied":
        problems += list_problems(pending.get("types_expected"), pending.get("bouquets_expected"))
        if pending.get("hd_services"):  # the box's own DB, not only its export
            try:
                now = {(s["sid"], s["name"].hex()): s for s in liveprog.services(liveprog.unpack(read_bytes(LIVE_PROG)))}
            except Exception as exc:  # noqa: BLE001
                now = {}
                problems.append(f"live_prog unreadable: {exc}")
            lost = [bytes.fromhex(h).decode("utf-8", "replace") for sid, h, t in pending["hd_services"]
                    if not (now.get((sid, h)) and now[(sid, h)]["type"] == t and not now[(sid, h)]["radio"]
                            and now[(sid, h)]["number"])]
            if lost:
                problems.append(f"HD services not TV in live_prog: {', '.join(lost[:6])}")
    else:
        problems += list_problems(pending.get("types_before"), pending.get("bouquets_before"))

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
        if mode == "repair-hd":
            if len(argv) < 3 or not os.path.isdir(os.path.join(argv[2], "enigma_db")):
                log("repair-hd needs a snapshot folder")
                return 2
            return repair_hd(argv[2])
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
