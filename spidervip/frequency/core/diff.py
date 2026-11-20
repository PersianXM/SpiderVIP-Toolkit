"""Compare one receiver satellite with its source satellite, carrier by carrier.

Matching: same polarization, frequency within ``freq_tol_mhz``; pairs are
assigned one-to-one, closest frequency first, then closest symbol rate.

Row kinds:
  same     matched, nothing to update
  changed  matched, the source has different parameters (updated in place)
  new      only in the source (appended to the satellite)
  gone     only on the receiver (candidate for deletion)
  skipped  only in the source but not representable on the box
           (multistream input-stream id / T2-MI), never added
  protected  would be changed or deleted, but the receiver has stored
           channels on it (lamedb); left as is — see core/lamedb.py

Source TPs are first put in the box's own form (L/R → H/V, whole MHz), so the
comparison reflects what the receiver will actually keep.

Change rules (source is authoritative, but "Auto" never overwrites a value):
  frequency    |Δ| ≥ 1 MHz
  symbol_rate  |Δ| ≥ 1 kS/s
  system       differs
  modulation   differs and source is not Auto (0)
  fec_inner    differs and source is not Auto (0)
Box-only fields (``mts``, ``plsN``) are never touched on existing TPs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .satxml import Satellite, Transponder, to_box_form

FREQ_TOL_MHZ = {"C": 3, "Ku": 3, "Ka": 5}
UPDATABLE = ("frequency", "symbol_rate", "system", "modulation", "fec_inner")
_AUTO_KEEP = ("modulation", "fec_inner")
_UNREPRESENTABLE = ("is_id", "t2mi_plp_id", "t2mi_pid")


@dataclass
class Row:
    kind: str
    box_pos: Optional[int] = None  # index in the receiver satellite's TP list
    box: Optional[Transponder] = None
    src: Optional[Transponder] = None
    changes: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    note: str = ""
    channels: bool = False  # a "gone" row whose TP carries stored channels (lamedb)


def unrepresentable(tp: Transponder) -> Optional[str]:
    """Reason a source TP cannot be written to the box, else None."""

    for key in _UNREPRESENTABLE:
        if key in tp.attrs and tp.attrs.get(key) not in ("", "-1"):
            return "multistream/T2-MI"
    # A non-default PLS code needs the box's mts/plsN pair, whose exact
    # semantics are not verified yet — report instead of guessing.
    if tp.attrs.get("pls_code") not in (None, "", "0", "1"):
        return "PLS"
    return None


def changes_for(box: Transponder, src: Transponder) -> Dict[str, Tuple[str, str]]:
    out: Dict[str, Tuple[str, str]] = {}
    if abs(src.freq_khz - box.freq_khz) >= 1000:
        out["frequency"] = (box.attrs.get("frequency", ""), src.attrs.get("frequency", ""))
    if abs(src.sr - box.sr) >= 1000:
        out["symbol_rate"] = (box.attrs.get("symbol_rate", ""), src.attrs.get("symbol_rate", ""))
    for key in ("system", "modulation", "fec_inner"):
        new = src.attrs.get(key)
        old = box.attrs.get(key)
        if new is None or new == old:
            continue
        if key in _AUTO_KEEP and new == "0":
            continue
        out[key] = (old or "", new)
    return out


PROTECTED_NOTE = "این TP کانال ذخیره‌شده دارد؛ برای به‌روزرسانی، آن را روی رسیور دوباره اسکن کنید."


def source_in_box_form(src_sat: Satellite) -> List[Transponder]:
    """Source TPs converted to box form, exact duplicates (freq/pol/SR) dropped."""

    out: List[Transponder] = []
    seen = set()
    for t in src_sat.tps:
        bt = to_box_form(t)
        key = (bt.freq_khz, bt.pol, bt.sr)
        if key in seen:
            continue
        seen.add(key)
        out.append(bt)
    return out


def compare(box_sat: Satellite, src_sat: Satellite, band: str = "Ku",
            protected: Optional[set] = None, delete_channel_tps: bool = False) -> List[Row]:
    """``protected``: indexes of receiver TPs that carry stored channels.

    With ``delete_channel_tps`` a channel TP missing from the source becomes a
    ``gone`` row flagged ``channels`` (its channels must also be removed from
    lamedb/bouquets, see ``lamedb.remove_transponders``); a changed channel TP
    stays ``protected`` either way.
    """

    protected = protected or set()
    tol_khz = FREQ_TOL_MHZ.get(band, 3) * 1000
    src_tps = source_in_box_form(src_sat)
    cands = []
    for bi, b in enumerate(box_sat.tps):
        for si, s in enumerate(src_tps):
            if b.pol != s.pol:
                continue
            df = abs(b.freq_khz - s.freq_khz)
            if df <= tol_khz:
                cands.append((df, abs(b.sr - s.sr), bi, si))
    cands.sort()
    box_used: Dict[int, int] = {}
    src_used = set()
    for _df, _dsr, bi, si in cands:
        if bi in box_used or si in src_used:
            continue
        box_used[bi] = si
        src_used.add(si)

    rows: List[Row] = []
    for bi, b in enumerate(box_sat.tps):
        si = box_used.get(bi)
        if si is None:
            if bi in protected and delete_channel_tps:
                rows.append(Row("gone", box_pos=bi, box=b, channels=True,
                                note="این TP کانال ذخیره‌شده دارد؛ با حذف آن، کانال‌هایش هم حذف می‌شوند."))
            elif bi in protected:
                rows.append(Row("protected", box_pos=bi, box=b, note=PROTECTED_NOTE))
            else:
                rows.append(Row("gone", box_pos=bi, box=b))
            continue
        s = src_tps[si]
        ch = changes_for(b, s)
        if ch and bi in protected:
            rows.append(Row("protected", box_pos=bi, box=b, src=s, changes=ch, note=PROTECTED_NOTE))
        else:
            rows.append(Row("changed" if ch else "same", box_pos=bi, box=b, src=s, changes=ch))
    extra = [s for si, s in enumerate(src_tps) if si not in src_used]
    extra.sort(key=lambda t: (t.freq_khz, t.pol))
    for s in extra:
        reason = unrepresentable(s)
        if reason:
            rows.append(Row("skipped", src=s, note=reason))
        else:
            rows.append(Row("new", src=s))
    return rows


def counts(rows: List[Row]) -> Dict[str, int]:
    out = {"same": 0, "changed": 0, "new": 0, "gone": 0, "skipped": 0, "protected": 0}
    for r in rows:
        out[r.kind] += 1
    return out
