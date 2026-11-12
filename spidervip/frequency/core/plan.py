"""Build a reviewable update plan and apply a selection of it to the box XML.

The plan is plain JSON (stored on the PC, later on the box) so the same file
can be reviewed in the Console, applied on the PC, or applied by the receiver.

Deletion guard (default selection only — the operator can override):
  deletions of a satellite are pre-selected only when the source looks like
  a complete list for it: the source has at least ``GUARD_MIN_SRC`` TPs and
  would remove at most ``GUARD_MAX_GONE_RATIO`` of the receiver's TPs.
  Otherwise the deletions are listed but left unticked.
Whole satellites (owner policy 2026-11-12):
  * source satellites with no receiver counterpart are offered as new
    satellites (``new_sats``, ids ``S<n>``) with all their TPs in box form;
  * receiver satellites with no source counterpart (``unmatched``) are offered
    for removal (ids ``X<box_index>``) only when no stored channel uses them.
  The Console pre-selects new satellites, not removals; the on-box update
  applies both (``full_selection``).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from typing import Dict, Iterable, List, Optional, Set

from . import diff as _diff
from . import lamedb as _lamedb
from . import pairing as _pairing
from . import satxml

PLAN_VERSION = 1
GUARD_MAX_GONE_RATIO = 0.5
GUARD_MIN_SRC = 3


class PlanError(RuntimeError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tp_view(tp: Optional[satxml.Transponder]) -> Optional[Dict[str, object]]:
    return tp.display() if tp is not None else None


def protected_indexes(sat: satxml.Satellite, channel_tps: List[_lamedb.LameTp]) -> Set[int]:
    """Indexes of ``sat`` TPs that carry stored channels (same position/pol, ±1 MHz, ±1 kS/s)."""

    here = [t for t in channel_tps if t.position == sat.position]
    out: Set[int] = set()
    for i, tp in enumerate(sat.tps):
        for t in here:
            if t.pol == tp.pol and abs(t.freq_khz - tp.freq_khz) <= 1000 and abs(t.sr - tp.sr) <= 1000:
                out.add(i)
                break
    return out


def _new_sat(src_index: int, ss: satxml.Satellite) -> Dict[str, object]:
    tps, seen = [], set()
    for tp in ss.tps:
        b = satxml.to_box_form(tp)
        key = (b.freq_khz, b.pol, b.sr)
        if key in seen:
            continue
        seen.add(key)
        tps.append(_new_tp_attrs(b.attrs))
    return {
        "id": f"S{src_index}",
        "src_index": src_index,
        "name": satxml.box_sat_name(ss.name),
        "src_name": ss.name,
        "position": ss.position,
        "position_label": satxml.position_label(ss.position),
        "band": _pairing.band(ss),
        "tps": tps,
        "count": len(tps),
        "default": True,
    }


def build(box_data: bytes, src_data: bytes, *, lamedb_data: Optional[bytes] = None,
          delete_channel_tps: bool = False,
          source_info: Optional[Dict[str, object]] = None,
          warnings: Optional[List[str]] = None) -> Dict[str, object]:
    """``lamedb_data``: the box's lamedb; TPs carrying channels are protected.

    Without it nothing is protected — only for offline use (download), never deploy.
    """

    box = satxml.parse(box_data)
    src = satxml.parse(src_data)
    pairs = _pairing.pair(box, src)
    lamedb_text = lamedb_data.decode("utf-8", "replace") if lamedb_data else ""
    channel_tps = _lamedb.channel_tps(lamedb_text) if lamedb_data else []
    svc = _lamedb.service_stats(lamedb_text) if lamedb_data else {"entries": 0, "unique": 0}

    sats_out: List[Dict[str, object]] = []
    unmatched: List[Dict[str, object]] = []
    totals = {"same": 0, "changed": 0, "new": 0, "gone": 0, "skipped": 0, "protected": 0,
              "gone_preselected": 0, "sats_paired": 0, "sats_unmatched": 0,
              "sats_with_changes": 0, "sats_new": 0, "sats_new_tps": 0,
              "sats_removable": 0, "sats_removable_tps": 0}
    channel_positions = {t.position for t in channel_tps}

    for p in pairs:
        bs = box[p.box_index]
        base = {
            "box_index": p.box_index,
            "name": bs.name,
            "position": bs.position,
            "position_label": satxml.position_label(bs.position),
            "band": p.band,
            "box_count": len(bs.tps),
        }
        if p.src_index is None:
            totals["sats_unmatched"] += 1
            has_channels = bs.position in channel_positions
            removable = bool(lamedb_data) and not has_channels
            base = dict(base, id=f"X{p.box_index}", channels=has_channels, removable=removable,
                        default=False)
            if removable:
                totals["sats_removable"] += 1
                totals["sats_removable_tps"] += len(bs.tps)
            unmatched.append(base)
            continue
        ss = src[p.src_index]
        rows = _diff.compare(bs, ss, p.band, protected_indexes(bs, channel_tps),
                             delete_channel_tps=delete_channel_tps)
        c = _diff.counts(rows)
        gone_ratio = c["gone"] / len(bs.tps) if bs.tps else 0.0
        guard_ok = len(ss.tps) >= GUARD_MIN_SRC and gone_ratio <= GUARD_MAX_GONE_RATIO
        if not c["gone"]:
            reason = ""
        elif guard_ok:
            reason = "منبع برای این ماهواره کامل به نظر می‌رسد؛ حذف‌ها پیش‌انتخاب شدند."
        else:
            reason = (f"منبع فقط {len(ss.tps)} TP دارد و {c['gone']} از {len(bs.tps)} TP رسیور "
                      f"({gone_ratio:.0%}) را حذف می‌کند؛ حذف‌ها پیش‌انتخاب نشدند.")
        rows_out = []
        n = {"changed": 0, "new": 0, "gone": 0, "skipped": 0, "protected": 0}
        for r in rows:
            if r.kind == "same":
                continue
            n[r.kind] += 1
            rid = f"{p.box_index}.{r.kind[0]}{n[r.kind]}"
            default = r.kind in ("changed", "new") or (r.kind == "gone" and guard_ok)
            rows_out.append({
                "id": rid,
                "kind": r.kind,
                "box_pos": r.box_pos,
                "box": _tp_view(r.box),
                "src": _tp_view(r.src),
                "src_attrs": dict(r.src.attrs) if r.src is not None else None,
                "box_attrs": dict(r.box.attrs) if r.box is not None else None,
                "changes": {k: [v[0], v[1]] for k, v in r.changes.items()},
                "note": r.note,
                "channels": r.channels,
                "default": default,
            })
        for k in ("same", "changed", "new", "gone", "skipped", "protected"):
            totals[k] += c[k]
        if guard_ok:
            totals["gone_preselected"] += c["gone"]
        totals["sats_paired"] += 1
        if c["changed"] or c["new"] or c["gone"]:
            totals["sats_with_changes"] += 1
        sats_out.append(dict(base, **{
            "src_name": ss.name,
            "src_position": ss.position,
            "pair": p.kind,
            "src_count": len(ss.tps),
            "counts": c,
            "guard": {"deletions_preselected": guard_ok, "reason": reason},
            "rows": rows_out,
        }))

    paired_src = {p.src_index for p in pairs if p.src_index is not None}
    new_sats = [_new_sat(si, ss) for si, ss in enumerate(src) if si not in paired_src and ss.tps]
    totals["sats_new"] = len(new_sats)
    totals["sats_new_tps"] = sum(s["count"] for s in new_sats)

    return {
        "version": PLAN_VERSION,
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "source": dict(source_info or {}),
        "warnings": list(warnings or []),
        "box": {"sha256": _sha(box_data), "bytes": len(box_data), "sats": len(box),
                "tps": satxml.total_tps(box),
                "lamedb_sha256": _sha(lamedb_data) if lamedb_data else None,
                "channel_tps": len(channel_tps),
                "channels": svc["unique"],
                "channel_entries": svc["entries"]},
        "totals": totals,
        "sats": sats_out,
        "unmatched": unmatched,
        "new_sats": new_sats,
    }


SELECTABLE = ("changed", "new", "gone")


def all_row_ids(plan: Dict[str, object]) -> Set[str]:
    """Ids that may be selected (protected/skipped rows are informational)."""

    ids = {r["id"] for s in plan["sats"] for r in s["rows"] if r["kind"] in SELECTABLE}
    ids |= {s["id"] for s in plan.get("new_sats", [])}
    ids |= {u["id"] for u in plan.get("unmatched", []) if u.get("removable")}
    return ids


def default_selection(plan: Dict[str, object]) -> Set[str]:
    ids = {r["id"] for s in plan["sats"] for r in s["rows"] if r["default"]}
    ids |= {s["id"] for s in plan.get("new_sats", []) if s.get("default")}
    return ids


def full_selection(plan: Dict[str, object]) -> Set[str]:
    """Every change, every new TP and every TP missing from the source (owner's
    policy for the automatic on-box update, 2026-11-11)."""

    return all_row_ids(plan)


def deleted_channel_tps(plan: Dict[str, object], selected: Iterable[str]):
    """``(position, freq_khz, pol, sr)`` of selected deletions that carry channels."""

    chosen = set(selected)
    out = []
    for s in plan["sats"]:
        for r in s["rows"]:
            if r["id"] in chosen and r["kind"] == "gone" and r.get("channels"):
                b = r["box_attrs"]
                out.append((s["position"], int(b["frequency"]), b["polarization"], int(b["symbol_rate"])))
    return out


def _new_tp_attrs(src_attrs: Dict[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key in satxml.BOX_TP_ATTR_ORDER:
        if key == "mts":
            out[key] = "0"
        elif key == "plsN":
            out[key] = "0"
        else:
            out[key] = src_attrs.get(key, "0")
    return out


def apply(box_data: bytes, plan: Dict[str, object], selected: Iterable[str]) -> Dict[str, object]:
    """Apply selected plan rows to ``box_data``; returns ``{xml, summary}``.

    Refuses when ``box_data`` is not the exact file the plan was built from.
    Paired satellites keep their element, name, attributes and order; only their
    transponders change. Selected removable satellites are dropped and selected
    new satellites are appended at the end (the box keeps its own table order).
    """

    if _sha(box_data) != plan["box"]["sha256"]:
        raise PlanError("لیست رسیور با لیستی که برنامه از آن ساخته شده یکی نیست؛ دوباره «بررسی» کنید.")
    chosen = set(selected)
    unknown = chosen - all_row_ids(plan)
    if unknown:
        raise PlanError(f"شناسه‌های ناشناخته در انتخاب: {sorted(unknown)[:5]}")

    sats = satxml.parse(box_data)
    summary = {"changed": 0, "new": 0, "gone": 0, "sats_touched": 0,
               "sats_added": [], "sats_removed": [], "sat_tps_added": 0, "sat_tps_removed": 0}
    for sp in plan["sats"]:
        sat = sats[sp["box_index"]]
        if sat.name != sp["name"] or sat.position != sp["position"]:
            raise PlanError(f"ترتیب ماهواره‌ها عوض شده است: {sp['name']}")
        drop: Set[int] = set()
        touched = False
        appended: List[satxml.Transponder] = []
        for row in sp["rows"]:
            if row["id"] not in chosen:
                continue
            kind = row["kind"]
            if kind == "changed":
                tp = sat.tps[row["box_pos"]]
                for key, (_old, new) in row["changes"].items():
                    tp.attrs[key] = new
                summary["changed"] += 1
                touched = True
            elif kind == "gone":
                drop.add(row["box_pos"])
                summary["gone"] += 1
                touched = True
            elif kind == "new":
                appended.append(satxml.Transponder(attrs=_new_tp_attrs(row["src_attrs"])))
                summary["new"] += 1
                touched = True
        if drop:
            sat.tps = [tp for i, tp in enumerate(sat.tps) if i not in drop]
        # New carriers go after the existing ones (existing TP positions stay put).
        sat.tps.extend(appended)
        if touched:
            summary["sats_touched"] += 1
    drop_sats: Set[int] = set()
    for u in plan.get("unmatched", []):
        if u.get("id") in chosen:
            sat = sats[u["box_index"]]
            if sat.name != u["name"] or sat.position != u["position"]:
                raise PlanError(f"ترتیب ماهواره‌ها عوض شده است: {u['name']}")
            drop_sats.add(u["box_index"])
            summary["sats_removed"].append(sat.name)
            summary["sat_tps_removed"] += len(sat.tps)
    if drop_sats:
        sats = [s for i, s in enumerate(sats) if i not in drop_sats]
    names = {(s.name, s.position) for s in sats}
    for ns in plan.get("new_sats", []):
        if ns["id"] not in chosen:
            continue
        if (ns["name"], ns["position"]) in names:
            raise PlanError(f"ماهوارهٔ تازه هم‌نام ماهواره‌ای در رسیور است: {ns['name']}")
        names.add((ns["name"], ns["position"]))
        sats.append(satxml.Satellite(
            attrs={"name": ns["name"], "flags": "0", "position": str(ns["position"])},
            tps=[satxml.Transponder(attrs=dict(a)) for a in ns["tps"]]))
        summary["sats_added"].append(ns["name"])
        summary["sat_tps_added"] += ns["count"]
    out = satxml.serialize(sats)
    summary["tps_before"] = plan["box"]["tps"]
    summary["tps_after"] = satxml.total_tps(sats)
    return {"xml": out, "summary": summary, "sha256": _sha(out)}
